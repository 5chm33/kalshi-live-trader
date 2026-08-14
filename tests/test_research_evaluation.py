from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.evaluate import evaluate
from research.models import PaperFill, PaperOrder, SourceStamp, payload_hash
from research.store import ResearchStore


class EvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stamp = SourceStamp(
            source="fixture", source_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
            received_at=datetime(2026, 8, 14, tzinfo=timezone.utc), payload_sha256=payload_hash({"x": 1}),
        )

    def test_evaluation_uses_only_recorded_settlements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            store.record_observation(self.stamp, "mlb_late_lead_candidate", "candidate-1", {
                "ticker": "MLB-YES", "inning": 8, "lead_runs": 3,
            })
            store.record_observation(self.stamp, "mlb_late_lead_candidate", "candidate-2", {
                "ticker": "MLB-UNSETTLED", "inning": 7, "lead_runs": 4,
            })
            store.record_settlement("MLB-YES", "yes", self.stamp, {"result": "yes"})
            order = PaperOrder(
                paper_order_id="order-1", strategy_version="test", ticker="MLB-YES", outcome_side="yes",
                requested_contracts=Decimal("1"), limit_price=Decimal("0.60"),
                signal_probability=Decimal("0.80"), expected_edge_before_cost=Decimal("0.20"),
                created_at=datetime.now(timezone.utc), metadata={},
            )
            store.record_order(order, None, "filled")
            store.record_fill(PaperFill(
                paper_order_id="order-1", ticker="MLB-YES", outcome_side="yes",
                filled_contracts=Decimal("1"), average_price=Decimal("0.60"),
                position_cost=Decimal("0.60"), estimated_fee=Decimal("0.02"),
                estimated_rounding_reserve=Decimal("0.01"), total_debit=Decimal("0.63"),
                model="fixture", created_at=datetime.now(timezone.utc), metadata={},
            ))
            report = evaluate(Path(directory) / "research.sqlite3")
            self.assertEqual(report["candidate_count"], 2)
            self.assertEqual(report["settled_candidate_count"], 1)
            self.assertEqual(report["unsettled_candidate_count"], 1)
            self.assertEqual(report["candidate_buckets"]["inning_8_lead_3"]["wins"], 1)
            self.assertEqual(report["settled_paper_fill_count"], 1)
            self.assertEqual(report["net_pnl"], "0.37")
            self.assertEqual(report["status"], "insufficient_data")


if __name__ == "__main__":
    unittest.main()
