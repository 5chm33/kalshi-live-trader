"""Read-only performance tests; no real credentials or requests."""
from __future__ import annotations

import unittest
from unittest.mock import Mock

from account_performance import paged, summarize
from core.kalshi_client import KalshiClient


class PerformanceTests(unittest.TestCase):
    def test_archive_is_account_wide_not_bot_attributed(self):
        client = Mock(spec=KalshiClient)
        client._request.side_effect = [
            {"market_positions": [{"ticker": "OPEN", "position_fp": "1.00"}], "cursor": ""},
            {"market_positions": [
                {"ticker": "A", "realized_pnl_dollars": "0.12", "fees_paid_dollars": "0.01"},
                {"ticker": "B", "realized_pnl_dollars": "-0.20", "fees_paid_dollars": "0.02"},
                {"ticker": "C", "realized_pnl_dollars": "0.00", "fees_paid_dollars": "0.00"}], "cursor": ""},
        ]
        result = summarize(client)
        self.assertEqual(result["archived_market_count"], 3)
        self.assertEqual(result["archived_reported_realized_pnl_dollars"], "-0.08")
        self.assertEqual(result["archived_positive_pnl_markets"], 1)
        self.assertEqual(result["archived_negative_pnl_markets"], 1)
        self.assertEqual(result["archived_nonflat_market_win_fraction"], "0.5")
        self.assertIn('UNAVAILABLE', result["bot_attribution"])

    def test_incomplete_page_aborts_instead_of_showing_partial_wins(self):
        client = Mock(spec=KalshiClient)
        client._request.side_effect = [
            {"market_positions": [{"ticker": "A"}], "cursor": "more"}, None]
        with self.assertRaisesRegex(RuntimeError, 'Cannot verify complete'):
            paged(client, '/historical/positions?limit=200', 'market_positions')

    def test_recent_historical_overlap_refused(self):
        client = Mock(spec=KalshiClient)
        client._request.side_effect = [
            {"market_positions": [{"ticker": "A", "position_fp": "0.00"}], "cursor": ""},
            {"market_positions": [{"ticker": "A", "realized_pnl_dollars": "1", "fees_paid_dollars": "0"}], "cursor": ""},
        ]
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            summarize(client)


if __name__ == '__main__':
    unittest.main()
