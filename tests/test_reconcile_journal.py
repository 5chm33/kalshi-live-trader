"""No-network venue reconciliation scenarios for durable local intents."""
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from core.execution_ledger import OrderLedger
from core.order_math import plan
from reconcile_journal import reconcile


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = OrderLedger(Path(self.tmp.name) / 'orders.sqlite')
        self.client = Mock()
        self.client.get_account_snapshot.return_value = {'cash_dollars': '9.90'}
        self.client.get_positions.return_value = []
        self.client.get_orders_by_status.return_value = []
        self.client.get_historical_market_orders.return_value = []
        self.client.get_market_fills.return_value = []
        self.ledger.prepare('one', 'KX-TEST', plan('yes', 'buy', 1, D('0.30')))

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_only_prepared_is_kept_without_probe_or_submit(self):
        rows = reconcile(self.client, self.ledger)
        self.assertEqual(rows[0]['phase'], 'prepared')
        self.client.get_orders_by_status.assert_not_called()
        self.client.place_order_v2.assert_not_called()

    def test_ambiguous_submission_is_not_retried(self):
        self.ledger.begin_submit('one')
        self.ledger.mark_uncertain('one', 'timeout')
        rows = reconcile(self.client, self.ledger)
        self.assertEqual(rows[0]['phase'], 'uncertain')
        self.client.place_order_v2.assert_not_called()

    def test_confirmed_unfilled_canceled_order_releases_reservation(self):
        self.ledger.begin_submit('one')
        order = {'client_order_id': 'one', 'order_id': 'venue-1', 'ticker': 'KX-TEST',
                 'book_side': 'bid', 'status': 'canceled', 'initial_count_fp': '1',
                 'fill_count_fp': '0', 'remaining_count_fp': '0',
                 'yes_price_dollars': '0.30', 'subaccount_number': 0}
        self.client.get_orders_by_status.side_effect = lambda ticker,status: ([order] if status=='canceled' else [])
        rows = reconcile(self.client, self.ledger)
        self.assertEqual(rows[0]['phase'], 'verified_flat')
        self.ledger.prepare('next', 'KX-TEST', plan('yes', 'buy', 1, D('0.30')))

    def test_historical_only_terminal_order_may_be_recovered(self):
        self.ledger.begin_submit('one')
        self.ledger.mark_uncertain('one', 'stale timeout')
        self.client.get_historical_market_orders.return_value = [
            {'client_order_id': 'one', 'order_id': 'archived-1', 'ticker': 'KX-TEST',
             'book_side': 'bid', 'status': 'canceled', 'initial_count_fp': '1',
             'fill_count_fp': '0', 'remaining_count_fp': '0',
             'yes_price_dollars': '0.30', 'subaccount_number': 0}]
        result = reconcile(self.client, self.ledger)
        self.assertEqual(result[0]['phase'], 'verified_flat')

    def test_partial_entry_persists_as_owned_inventory(self):
        self.ledger.begin_submit('one')
        order = {'client_order_id': 'one', 'order_id': 'venue-1', 'ticker': 'KX-TEST',
                 'book_side': 'bid', 'status': 'canceled', 'initial_count_fp': '1',
                 'fill_count_fp': '1', 'remaining_count_fp': '0',
                 'yes_price_dollars': '0.30', 'subaccount_number': 0}
        fill = {'fill_id': 'fill-1', 'order_id': 'venue-1', 'count_fp': '1',
                'yes_price_dollars': '0.30', 'fee_cost': '0.01', 'subaccount_number': 0}
        self.client.get_positions.return_value = [{'ticker':'KX-TEST','position_fp':'1'}]
        self.client.get_orders_by_status.side_effect = lambda ticker,status: ([order] if status=='canceled' else [])
        self.client.get_market_fills.side_effect = lambda ticker,historical=False: ([fill] if historical else [])
        rows = reconcile(self.client, self.ledger)
        self.assertEqual(rows[0]['phase'], 'reconcile')
        self.assertEqual(self.ledger.filled_quantity('one'), D('1'))
        self.client.place_order_v2.assert_not_called()

    def test_account_read_error_does_not_release_anything(self):
        self.ledger.begin_submit('one')
        self.client.get_positions.side_effect = RuntimeError('GET failed')
        with self.assertRaises(RuntimeError):
            reconcile(self.client, self.ledger)
        self.assertEqual(self.ledger.snapshot('one')['phase'], 'submitting')


if __name__ == '__main__':
    unittest.main()
