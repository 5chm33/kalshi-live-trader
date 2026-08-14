from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from research.directional_parity import assess_directional_cover, is_directional_upper_tail
from research.models import BookLevel, CanonicalBook, SourceStamp


def book(ticker, yes_bids, no_bids):
    return CanonicalBook(
        ticker=ticker,
        yes_bids=tuple(BookLevel(Decimal(p), Decimal(q)) for p, q in yes_bids),
        no_bids=tuple(BookLevel(Decimal(p), Decimal(q)) for p, q in no_bids),
        stamp=SourceStamp("test", datetime.now(timezone.utc), None, "test"),
    )


class DirectionalParityTests(unittest.TestCase):
    def test_api_strike_metadata_is_required(self):
        self.assertTrue(is_directional_upper_tail({"market_type": "binary", "status": "active", "floor_strike": 50, "cap_strike": None}))
        self.assertFalse(is_directional_upper_tail({"market_type": "binary", "status": "active", "floor_strike": 50, "cap_strike": 51}))

    def test_cover_candidate_requires_costs_below_one(self):
        outcome = assess_directional_cover(
            book("LOW", [], [("0.70", "2")]), book("HIGH", [("0.70", "2")], []),
            "50", "60", fee_multiplier="0.01", atomicity_reserve_per_contract="0.001", min_locked_profit_per_contract="0.005",
        )
        self.assertTrue(outcome.is_candidate)
        self.assertLess(outcome.total_debit, Decimal("1"))

    def test_invalid_threshold_order_is_rejected(self):
        with self.assertRaises(ValueError):
            assess_directional_cover(book("A", [], [("0.6", "1")]), book("B", [("0.6", "1")], []), "60", "50")


if __name__ == "__main__":
    unittest.main()
