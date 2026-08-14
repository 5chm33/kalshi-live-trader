from decimal import Decimal
import unittest

from research.economics import empirical_streak_summary, entry_to_exit, entry_to_settlement


class EconomicsTests(unittest.TestCase):
    def test_settlement_and_exit_lifecycles_are_distinct(self) -> None:
        settlement = entry_to_settlement(Decimal("2"), Decimal("1.10"), True, Decimal("86400"))
        exit_ = entry_to_exit(Decimal("2"), Decimal("1.10"), Decimal("1.40"), Decimal("3600"))
        self.assertEqual("0.90", str(settlement.net_pnl))
        self.assertEqual("0.30", str(exit_.net_pnl))
        self.assertEqual("0.45", str(settlement.dollars_per_contract))
        self.assertEqual("0.2727272727272727272727272727", str(exit_.return_on_locked_capital))
        self.assertNotEqual(settlement.lifecycle, exit_.lifecycle)

    def test_observed_streak_summary_does_not_simulate(self) -> None:
        report = empirical_streak_summary(
            [Decimal("-0.10"), Decimal("-0.20"), Decimal("0.03"), Decimal("-0.40")], Decimal("1.00")
        )
        self.assertEqual(2, report["observed_longest_loss_streak"])
        self.assertEqual(Decimal("0.40"), report["observed_worst_consecutive_loss_dollars"])
        self.assertEqual(Decimal("0.60"), report["bankroll_after_observed_worst_streak"])


if __name__ == "__main__":
    unittest.main()
