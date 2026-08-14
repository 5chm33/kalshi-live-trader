from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from research.liquidity import LiquidityPolicy, liquidity_report
from research.models import BookLevel, CanonicalBook, SourceStamp
from research.placebo import paired_placebo_report
from research.statistical_gates import GatePolicy, calibration_error, one_sided_wilson_lower, promotion_gate


class StatisticalControlTests(unittest.TestCase):
    def book(self, yes_bid: str, no_bid: str, qty: str) -> CanonicalBook:
        stamp = SourceStamp("test", datetime.now(timezone.utc), None, "h")
        return CanonicalBook("T", (BookLevel(Decimal(yes_bid), Decimal(qty)),), (BookLevel(Decimal(no_bid), Decimal(qty)),), stamp)

    def test_wilson_and_promotion_gate_are_conservative(self) -> None:
        self.assertIsNone(one_sided_wilson_lower(0, 0))
        lcb = one_sided_wilson_lower(9, 10)
        self.assertLess(lcb, Decimal("0.9"))
        policy = GatePolicy(20, 1, Decimal("0.02"), Decimal("0"))
        result = promotion_gate(policy, 10, Decimal("0.01"), Decimal("0.02"), 1)
        self.assertFalse(result["eligible"])
        self.assertIn("insufficient_independent_clusters", result["failures"])

    def test_calibration_error_and_liquidity_reject_wide_shallow_books(self) -> None:
        self.assertEqual(Decimal("0.1"), calibration_error([Decimal("0.9")], [1]))
        report = liquidity_report([self.book("0.40", "0.40", "0.5")], "yes", LiquidityPolicy(2, Decimal("0.05"), Decimal("1"), Decimal("1")))
        self.assertFalse(report["eligible"])
        self.assertIn("insufficient_book_observations", report["failures"])
        self.assertIn("insufficient_top_of_book_depth", report["failures"])

    def test_placebo_is_never_executable_evidence(self) -> None:
        report = paired_placebo_report([Decimal("0.03"), Decimal("0.01")], [Decimal("0.02"), Decimal("0")], "one_period_shift")
        self.assertFalse(report["executable"])
        self.assertEqual("exploratory_control_only", report["status"])


if __name__ == "__main__":
    unittest.main()
