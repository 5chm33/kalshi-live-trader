"""Synthetic fixtures test parser/math only; they are never performance samples."""
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from core.microstructure import scheduled_start, effective_fees, paired_book, fee_estimate
from core.public_market import MarketDataError


RULE = ('If Chicago C wins the Chicago C vs Boston professional baseball game '
        'originally scheduled for Sep 26, 2026 at 7:15 PM EDT, then the market resolves to Yes.')


def market(ticker='X-A', rules=RULE):
    return {'ticker': ticker, 'event_ticker': 'X', 'status': 'active',
            'rules_primary': rules, 'price_ranges': [
                {'start': '0.0000', 'end': '1.0000', 'step': '0.0100'}]}


def book(yes='0.53', no='0.45', yes_size='10.00'):
    return {'yes_dollars': [[yes, yes_size]], 'no_dollars': [[no, '10.00']]}


class MLBMicrostructureTests(unittest.TestCase):
    def setUp(self):
        self.markets = [market(), market('X-B')]
        self.series = {'ticker': 'KXMLBGAME', 'fee_type': 'quadratic_with_maker_fees', 'fee_multiplier': 0.5}
        self.event = {'event_ticker': 'X', 'series_ticker': 'KXMLBGAME', 'mutually_exclusive': True}

    def test_rule_time_not_occurrence_or_expiration(self):
        self.markets[0]['occurrence_datetime'] = '2026-09-27T02:15:00Z'
        self.assertEqual(scheduled_start(self.markets), datetime(2026, 9, 26, 23, 15, tzinfo=timezone.utc))

    def test_bad_or_mismatched_rule_fails_closed(self):
        self.markets[1]['rules_primary'] = RULE.replace('7:15', '8:15')
        with self.assertRaises(MarketDataError): scheduled_start(self.markets)
        self.markets[1]['rules_primary'] = 'scheduled at noon'
        with self.assertRaises(MarketDataError): scheduled_start(self.markets)

    def test_live_series_multiplier_and_override(self):
        self.assertEqual(effective_fees(self.series, self.event), ('quadratic_with_maker_fees', Decimal('0.5')))
        self.event['fee_multiplier_override'] = 0
        self.assertEqual(effective_fees(self.series, self.event)[1], Decimal('0'))
        self.event['fee_type_override'] = 'flat'
        with self.assertRaises(MarketDataError): effective_fees(self.series, self.event)

    def test_conservative_cents_do_not_present_gross_spread_as_profit(self):
        mark = paired_book(self.markets, [book(), book(yes='0.45', no='0.53')], self.series, self.event)
        self.assertTrue(mark['eligible'])
        self.assertEqual(mark['conditional_gross_spread_dollars'], '0.02')
        self.assertEqual(mark['conservative_non_direct_maker_fee_dollars'], '0.02')
        self.assertEqual(mark['conditional_paired_mark_dollars'], '0.00')
        self.assertTrue(mark['not_a_fill'])

    def test_unavailable_or_thin_side_never_becomes_pair(self):
        self.assertEqual(paired_book(self.markets, [book(), book(yes='0.45', yes_size='0.40')],
                                     self.series, self.event)['reason'], 'insufficient_yes_bid_depth')
        self.assertEqual(paired_book(self.markets, [book(), {'yes_dollars': [], 'no_dollars': []}],
                                     self.series, self.event)['reason'], 'one_sided_or_empty')

    def test_off_grid_and_crossed_book_fail(self):
        with self.assertRaises(MarketDataError):
            paired_book(self.markets, [book(yes='0.535'), book()], self.series, self.event)
        with self.assertRaises(MarketDataError):
            paired_book(self.markets, [book(yes='0.65', no='0.45'), book()], self.series, self.event)

    def test_non_direct_conservative_rounding(self):
        self.assertEqual(fee_estimate(Decimal('0.50'), 'quadratic_with_maker_fees', Decimal('0.5'), maker=True), Decimal('0.01'))
        self.assertEqual(fee_estimate(Decimal('0.50'), 'quadratic', Decimal('0.5'), maker=True), Decimal('0'))
        self.assertEqual(fee_estimate(Decimal('0.50'), 'quadratic', Decimal('0.5'), maker=False), Decimal('0.01'))
        self.assertEqual(fee_estimate(Decimal('0.539'), 'quadratic_with_maker_fees', Decimal('0.5'), maker=True), Decimal('0.011'))
        self.assertEqual(fee_estimate(Decimal('0.539'), 'quadratic', Decimal('0.5'), maker=True), Decimal('0.001'))


if __name__ == '__main__':
    unittest.main()
