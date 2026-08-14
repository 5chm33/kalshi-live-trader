from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.mlb_oos import evaluate_out_of_sample
from research.models import SourceStamp, payload_hash
from research.store import ResearchStore


class MLBOOSTests(unittest.TestCase):
    def _stamp(self, key: str) -> SourceStamp:
        return SourceStamp("test", datetime.now(timezone.utc), None, payload_hash({"key": key}))

    @staticmethod
    def _row(game: str, index: int, day: str, won: bool) -> dict[str, object]:
        return {
            "game_pk": game, "at_bat_index": index, "game_date": day,
            "inning": 7, "inning_half": "top", "outs": 1,
            "leader_is_home": True, "lead_runs": 3,
            "away_runs": 1, "home_runs": 4, "leader_won": won,
        }

    def test_out_of_sample_metrics_use_train_only_probabilities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            for index in range(30):
                store.record_mlb_historical_state(self._row(f"train-{index}", 1, "2025-06-01", index < 27), self._stamp(f"t{index}"))
            for index in range(4):
                store.record_mlb_historical_state(self._row(f"test-{index}", 1, "2025-07-01", index < 3), self._stamp(f"v{index}"))
            report = evaluate_out_of_sample(store.path, "2025-06-30", "2025-07-01", "2025-07-31", minimum_games=30)
            self.assertEqual(report["status"], "descriptive_probability_evaluation_only")
            self.assertEqual(report["eligible_states"], 4)
            self.assertIn("brier_score", report)
            self.assertIn("log_loss", report)
            self.assertEqual(report["trading_profitability_inference"], "not_available_without_time-aligned Kalshi quote/fill data")

    def test_oos_with_only_sparse_training_buckets_is_ineligible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            store.record_mlb_historical_state(self._row("train", 1, "2025-06-01", True), self._stamp("train"))
            store.record_mlb_historical_state(self._row("test", 1, "2025-07-01", True), self._stamp("test"))
            report = evaluate_out_of_sample(store.path, "2025-06-30", "2025-07-01", "2025-07-31", minimum_games=30)
            self.assertEqual(report["status"], "insufficient_eligible_out_of_sample_data")


if __name__ == "__main__":
    unittest.main()
