from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from research.mec_no_basket import assess_mec_no_basket
from research.models import BookLevel, CanonicalBook, SourceStamp


def book(ticker: str, yes_bid: str) -> CanonicalBook:
    return CanonicalBook(
        ticker=ticker, yes_bids=(BookLevel(Decimal(yes_bid), Decimal("3")),), no_bids=(),
        stamp=SourceStamp("test", datetime.now(timezone.utc), None, "test"),
    )


class MecNoBasketTests(unittest.TestCase):
    def test_two_leg_basket_uses_one_contract_minimum_payout(self):
        assessments = assess_mec_no_basket(
            "EVENT", {"A": book("A", "0.70"), "B": book("B", "0.70")},
            fee_multiplier="0.01", atomicity_reserve_per_leg_contract="0.001", min_locked_profit_per_contract="0.005",
        )
        self.assertEqual(len(assessments), 1)
        result = assessments[0]
        self.assertEqual(result.guaranteed_payout_floor, Decimal("1"))
        self.assertTrue(result.is_candidate)

    def test_three_leg_basket_requires_actual_fee_adjusted_edge(self):
        assessments = assess_mec_no_basket(
            "EVENT", {"A": book("A", "0.34"), "B": book("B", "0.34"), "C": book("C", "0.34")},
            fee_multiplier="1", atomicity_reserve_per_leg_contract="0.01",
        )
        self.assertFalse(assessments[-1].is_candidate)
        self.assertEqual(assessments[-1].guaranteed_payout_floor, Decimal("2"))

    def test_insufficient_depth_leg_is_excluded(self):
        shallow = CanonicalBook("C", (), (), SourceStamp("test", datetime.now(timezone.utc), None, "test"))
        assessments = assess_mec_no_basket("EVENT", {"A": book("A", "0.70"), "B": book("B", "0.70"), "C": shallow})
        self.assertEqual(len(assessments), 1)
        self.assertEqual(assessments[0].tickers, ("A", "B"))


if __name__ == "__main__":
    unittest.main()
