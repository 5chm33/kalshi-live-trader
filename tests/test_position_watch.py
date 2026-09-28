"""No-network tests for authenticated fill/position/book viewer."""
from unittest import TestCase
from unittest.mock import Mock

from position_watch import inspect_positions


class PositionWatchTests(TestCase):
    def setUp(self):
        self.account = Mock()
        self.public = Mock()
        self.account.get_positions.return_value = [{"ticker": "KX-EXAMPLE", "position_fp": "1.00"}]
        self.fills = [{"ticker": "KX-EXAMPLE",
            "order_id": "order-1", "fill_id": "fill-1", "book_side": "bid",
            "count_fp": "1.00", "yes_price_dollars": "0.4000", "fee_cost": "0.01",
            "subaccount_number": 0}]
        self.account.get_market_fills.side_effect = lambda ticker, historical=False: ([] if historical else self.fills)
        self.public.get_orderbook.return_value = {"yes_dollars": [["0.4800", "3.00"]],
                                                   "no_dollars": [["0.5000", "5.00"]]}

    def test_real_fill_and_executable_bid_mark(self):
        result = inspect_positions(self.account, self.public)[0]
        self.assertEqual(result["status"], "valued")
        self.assertEqual(result["realized_pnl_from_confirmed_fills"], "0.0000")
        self.assertEqual(result["executable_bid"], "0.4800")
        self.account.place_ioc.assert_not_called()

    def test_historical_tier_can_explain_current_position(self):
        self.account.get_market_fills.side_effect = lambda ticker, historical=False: (self.fills if historical else [])
        result = inspect_positions(self.account, self.public)[0]
        self.assertEqual(result["status"], "valued")
        self.assertEqual(self.account.get_market_fills.call_count, 2)

    def test_mismatch_or_missing_book_never_reports_zero_pnl(self):
        self.account.get_positions.return_value = [{"ticker": "KX-EXAMPLE", "position_fp": "2.00"}]
        result = inspect_positions(self.account, self.public)[0]
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("estimated_total_pnl", result)
        self.account.get_positions.return_value = [{"ticker": "KX-EXAMPLE", "position_fp": "1.00"}]
        self.public.get_orderbook.return_value = {"yes_dollars": [], "no_dollars": []}
        result = inspect_positions(self.account, self.public)[0]
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("estimated_total_pnl", result)

    def test_untrusted_prior_exit_history_abstains(self):
        self.fills.append({
            "ticker": "KX-EXAMPLE", "order_id": "order-2", "fill_id": "fill-2",
            "book_side": "ask", "count_fp": "1", "yes_price_dollars": "0.50",
            "fee_cost": "0.01", "subaccount_number": 0})
        self.account.get_positions.return_value = [{"ticker": "KX-EXAMPLE", "position_fp": "0.00"}]
        with self.assertRaises(ValueError):
            inspect_positions(self.account, self.public)

    def test_other_or_missing_subaccount_fills_cannot_set_primary_cost_basis(self):
        self.fills[0]['subaccount_number'] = 1
        self.assertEqual(inspect_positions(self.account, self.public)[0]['status'], 'unavailable')
        del self.fills[0]['subaccount_number']
        result = inspect_positions(self.account, self.public)[0]
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('subaccount', result['reason'])


if __name__ == '__main__':
    import unittest
    unittest.main()
