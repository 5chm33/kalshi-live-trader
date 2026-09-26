"""Synthetic pilot safety fixtures; NOT evidence of live profitability."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import Mock, patch

from core.execution_ledger import LedgerError, OrderLedger
from core.order_math import plan
from core.pilot_venue import MLB_SHARD, ScopedVenue, VenueError
from pilot_live import reconcile_one, safe_pilot_account, submit_one, choose_candidate, run


class PilotVenueTests(unittest.TestCase):
    def setUp(self):
        self.venue = ScopedVenue.__new__(ScopedVenue)
        self.venue.subaccount = 1
        self.venue.client = Mock()
        self.venue.client.base_url = 'https://external-api.kalshi.com'
        self.venue.client._auth_headers.return_value = {'KALSHI-ACCESS-KEY': 'mock'}

    def payload(self):
        return plan('yes', 'buy', 1, D('0.4500')).payload(
            'KXMLBGAME-TEST-TEAM', 'pilot-test-1234', subaccount=1, exchange_index=MLB_SHARD)

    def test_post_once_uses_tls_no_redirect_and_numbered_shard(self):
        response = Mock(status_code=201)
        response.json.return_value = {'order_id': 'order-test-1234', 'client_order_id': 'pilot-test-1234',
                                      'fill_count': '1.00', 'remaining_count': '0.00'}
        self.venue.client.session.post.return_value = response
        result = self.venue.submit_ioc(self.payload())
        self.assertEqual(result['fill_count'], '1.00')
        self.venue.client.session.post.assert_called_once()
        self.assertEqual(self.venue.client.session.post.call_args.kwargs['allow_redirects'], False)
        self.assertEqual(self.venue.client.session.post.call_args.kwargs['verify'], True)
        self.assertEqual(self.venue.client.session.post.call_args.kwargs['json']['subaccount'], 1)
        self.assertEqual(self.venue.client.session.post.call_args.kwargs['json']['exchange_index'], 3)

    def test_wrong_shard_high_price_or_post_timeout_never_retries(self):
        for patch in ({'exchange_index': 0}, {'subaccount': 0}, {'price': '0.6000'},
                      {'count': '2.00'}, {'time_in_force': 'good_till_canceled'}):
            with self.subTest(patch=patch), self.assertRaises(VenueError):
                self.venue.submit_ioc(dict(self.payload(), **patch))
        self.venue.client.session.post.assert_not_called()
        self.venue.client.session.post.side_effect = TimeoutError('network')
        with self.assertRaisesRegex(VenueError, 'uncertain'):
            self.venue.submit_ioc(self.payload())
        self.venue.client.session.post.assert_called_once()

    def test_only_verified_own_resting_order_may_be_canceled(self):
        row = {'order_id': 'order-test-1234', 'client_order_id': 'pilot-test-1234',
               'ticker': 'KXMLBGAME-TEST-TEAM', 'status': 'resting',
               'subaccount_number': 1, 'exchange_index': 3}
        for bad in ({'subaccount_number': 0}, {'exchange_index': 0},
                    {'client_order_id': 'other'}, {'status': 'executed'}):
            with self.subTest(bad=bad), self.assertRaises(VenueError):
                self.venue.cancel_owned_resting(dict(row, **bad), 'pilot-test-1234')
        self.venue.client.session.delete.assert_not_called()
        response = Mock(status_code=200)
        response.json.return_value = {'order_id': row['order_id'], 'client_order_id': row['client_order_id']}
        self.venue.client.session.delete.return_value = response
        self.venue.cancel_owned_resting(row, 'pilot-test-1234')
        self.venue.client.session.delete.assert_called_once()

    def test_scoped_cash_positions_orders_and_fills(self):
        self.venue.get = Mock(return_value={'balance_dollars': '2.0000'})
        self.assertEqual(self.venue.cash(), D('2'))
        self.assertIn('exchange_index=3', self.venue.get.call_args.args[0])
        self.venue.pages = Mock(return_value=[{'ticker': 'KX-TEST', 'position_fp': '1.00',
                                               'exchange_index': 0}])
        with self.assertRaises(VenueError):
            self.venue.positions()
        self.venue.pages.return_value = [{'order_id': 'e', 'subaccount_number': 0, 'exchange_index': 3}]
        with self.assertRaises(VenueError):
            self.venue.orders(status='resting')
        self.venue.pages.return_value = [{'fill_id': 'f', 'order_id': 'abc-1234',
                                          'subaccount_number': 1, 'exchange_index': 0}]
        with self.assertRaises(VenueError):
            self.venue.fills('KX-TEST', 'abc-1234')


class PilotJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = OrderLedger(Path(self.temp.name) / 'pilot.sqlite', subaccount=1,
                                  max_entry_attempts_per_day=1)
        self.venue = Mock(subaccount=1)
        self.venue.cash.return_value = D('2.00')
        self.venue.positions.return_value = []
        self.venue.orders.return_value = []
        self.ticker = 'KXMLBGAME-TEST-TEAM'

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def test_preflight_rejects_existing_inventory_orders_and_too_much_cash(self):
        self.assertEqual(safe_pilot_account(self.venue, self.ledger, before_entry=True), D(2))
        self.venue.orders.return_value = [{'order_id': 'other'}]
        with self.assertRaises(VenueError):
            safe_pilot_account(self.venue, self.ledger, before_entry=True)
        self.venue.orders.return_value = []
        self.venue.cash.return_value = D('2.01')
        with self.assertRaises(VenueError):
            safe_pilot_account(self.venue, self.ledger, before_entry=True)

    def test_submit_uncertainty_persists_and_never_sends_second_order(self):
        self.venue.submit_ioc.side_effect = TimeoutError('ambiguous')
        with self.assertRaisesRegex(VenueError, 'uncertain'):
            submit_one(self.venue, self.ledger, self.ticker, D('.45'), action='buy')
        self.venue.submit_ioc.assert_called_once()
        rows = self.ledger.db.execute("SELECT client_id, phase FROM intents").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['phase'], 'uncertain')
        with self.assertRaises(LedgerError):
            self.ledger.prepare('another', self.ticker, plan('yes', 'buy', 1, D('.44')))

    def test_actual_zero_fill_is_verified_not_guessed(self):
        cid = 'pilot-test-1234'
        self.ledger.prepare(cid, self.ticker, plan('yes', 'buy', 1, D('.45')))
        self.ledger.begin_submit(cid)
        self.ledger.record_ack(cid, {'client_order_id': cid, 'order_id': 'exchange-1234',
                                     'fill_count': '0.00', 'remaining_count': '0.00'})
        row = {'client_order_id': cid, 'order_id': 'exchange-1234', 'ticker': self.ticker,
               'book_side': 'bid', 'yes_price_dollars': '0.4500', 'initial_count_fp': '1.00',
               'fill_count_fp': '0.00', 'remaining_count_fp': '0.00', 'status': 'canceled',
               'subaccount_number': 1, 'exchange_index': 3}
        self.venue.orders.side_effect = lambda **kwargs: [row] if kwargs['status'] == 'canceled' else []
        self.venue.fills.return_value = []
        self.assertEqual(reconcile_one(self.venue, self.ledger, cid)['phase'], 'verified_flat')
        with self.assertRaises(LedgerError):
            self.ledger.begin_submit(cid)
        outcome = run(self.venue, Mock(), self.ledger, deadline=datetime.now(timezone.utc)+timedelta(minutes=1))
        self.assertEqual(outcome['status'], 'verified_zero_fill')
        self.assertEqual(self.venue.submit_ioc.call_count, 0)

    def test_absent_order_stays_uncertain(self):
        cid = 'pilot-test-1234'
        self.ledger.prepare(cid, self.ticker, plan('yes', 'buy', 1, D('.45')))
        self.ledger.begin_submit(cid)
        with self.assertRaisesRegex(VenueError, 'Cannot uniquely recover'):
            reconcile_one(self.venue, self.ledger, cid)
        self.assertEqual(self.ledger.snapshot(cid)['phase'], 'uncertain')


class CandidateTests(unittest.TestCase):
    def test_wrong_shard_or_thin_book_never_becomes_a_candidate(self):
        at = datetime.now(timezone.utc)
        first = at + timedelta(hours=2)
        pair = [{'ticker': 'KXMLBGAME-TEST-A', 'event_ticker': 'KXMLBGAME-TEST',
                 'status': 'active', 'exchange_index': 3},
                {'ticker': 'KXMLBGAME-TEST-B', 'event_ticker': 'KXMLBGAME-TEST',
                 'status': 'active', 'exchange_index': 3}]
        public = Mock()
        public.get_markets.return_value = pair
        public.get_series.return_value = {'ticker': 'KXMLBGAME'}
        public.get_event.return_value = {'event_ticker': 'KXMLBGAME-TEST',
                                         'exchange_index': 3, 'mutually_exclusive': True}
        public.get_orderbook.return_value = {'orderbook_fp': {}}
        quote = Mock(yes_bid=D('.42'), no_bid=D('.56'), yes_ask=D('.44'),
                     yes_ask_size=D('3'), no_ask_size=D('2'))
        with (patch('pilot_live.scheduled_start', return_value=first),
              patch('pilot_live.quote_from_orderbook', return_value=quote),
              patch('pilot_live._grid_check'),
              patch('pilot_live.effective_fees', return_value=('quadratic', D('.5'))),
              patch('pilot_live.fee_estimate', return_value=D('.02'))):
            self.assertEqual(choose_candidate(public, at)['ticker'], pair[0]['ticker'])
            public.get_orderbook.assert_called_once()
            public.get_orderbook.reset_mock()
            quote.yes_ask_size = D('.5')
            self.assertIsNone(choose_candidate(public, at))
            public.get_orderbook.reset_mock()
            quote.yes_ask_size = D('2')
            pair[0]['exchange_index'] = pair[1]['exchange_index'] = 0
            self.assertIsNone(choose_candidate(public, at))
            public.get_orderbook.assert_not_called()


if __name__ == '__main__':
    unittest.main()
