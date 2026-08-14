from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from research.expectancy import assess
from research.models import PaperFill, SourceStamp, StrategySignal, payload_hash


class ExpectancyTests(unittest.TestCase):
    def _signal(self) -> StrategySignal:
        stamp = SourceStamp("test", datetime.now(timezone.utc), None, payload_hash({"test": True}))
        return StrategySignal(
            signal_id="signal", strategy="test", strategy_version="v1", ticker="TEST", outcome_side="yes",
            model_probability=Decimal("0.80"), conservative_probability=Decimal("0.75"),
            observed_price=Decimal("0.60"), requested_contracts=Decimal("2"), source_stamp=stamp,
            rationale="test", features={},
        )

    def _fill(self, debit: str = "1.24") -> PaperFill:
        return PaperFill(
            paper_order_id="order", ticker="TEST", outcome_side="yes", filled_contracts=Decimal("2"),
            average_price=Decimal("0.60"), position_cost=Decimal("1.20"), estimated_fee=Decimal("0.03"),
            estimated_rounding_reserve=Decimal("0.01"), total_debit=Decimal(debit), model="test",
            created_at=datetime.now(timezone.utc), metadata={},
        )

    def test_assessment_includes_full_debit_and_requires_minimum_net(self) -> None:
        assessment = assess(self._signal(), self._fill())
        self.assertEqual(assessment.expected_settlement_payout, Decimal("1.50"))
        self.assertEqual(assessment.expected_net_pnl, Decimal("0.26"))
        self.assertTrue(assessment.eligible)

    def test_no_fill_is_not_an_opportunity(self) -> None:
        assessment = assess(self._signal(), None)
        self.assertFalse(assessment.eligible)
        self.assertEqual(assessment.reason, "no_executable_displayed_depth")

    def test_fee_depth_adjusted_loss_is_rejected(self) -> None:
        assessment = assess(self._signal(), self._fill("1.49"))
        self.assertFalse(assessment.eligible)
        self.assertEqual(assessment.reason, "fee_depth_adjusted_ev_below_threshold")


if __name__ == "__main__":
    unittest.main()
