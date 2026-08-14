from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from research.binary_parity import assess_complement_parity
from research.models import BookLevel, CanonicalBook, SourceStamp


def book(yes_bids, no_bids) -> CanonicalBook:
    return CanonicalBook(
        ticker="KXTEST-TEST", yes_bids=tuple(BookLevel(Decimal(p), Decimal(q)) for p, q in yes_bids),
        no_bids=tuple(BookLevel(Decimal(p), Decimal(q)) for p, q in no_bids),
        stamp=SourceStamp("test", datetime.now(timezone.utc), None, "test"),
    )


class BinaryParityTests(unittest.TestCase):
    def test_candidate_requires_net_profit_after_two_leg_costs(self) -> None:
        # YES ask=0.40 (NO bid=0.60); NO ask=0.40 (YES bid=0.60).
        outcome = assess_complement_parity(
            book([("0.60", "2")], [("0.60", "2")]),
            fee_multiplier="0.01", atomicity_reserve_per_contract="0.001", min_locked_profit_per_contract="0.005",
        )
        self.assertTrue(outcome.is_candidate)
        self.assertEqual(outcome.matched_contracts, Decimal("1"))
        self.assertLess(outcome.total_debit, Decimal("1"))

    def test_two_leg_fees_can_remove_apparent_price_edge(self) -> None:
        outcome = assess_complement_parity(
            book([("0.51", "2")], [("0.51", "2")]),
            fee_multiplier="1", atomicity_reserve_per_contract="0.01", min_locked_profit_per_contract="0.005",
        )
        self.assertFalse(outcome.is_candidate)
        self.assertEqual(outcome.status, "not_profitable_after_costs")

    def test_partial_complement_depth_is_rejected(self) -> None:
        outcome = assess_complement_parity(book([("0.70", "1")], [("0.70", "2")]), requested_contracts="2")
        self.assertEqual(outcome.status, "ineligible_partial_matched_depth")


if __name__ == "__main__":
    unittest.main()
