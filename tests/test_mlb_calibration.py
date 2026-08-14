from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.mlb_calibration import EmpiricalMLBModel
from research.models import SourceStamp, payload_hash
from research.store import ResearchStore


class MLBCalibrationTests(unittest.TestCase):
    def _stamp(self, value: object) -> SourceStamp:
        return SourceStamp("test", datetime.now(timezone.utc), None, payload_hash({"value": str(value)}))

    def test_repeated_states_in_one_game_count_once_per_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            for game_number in range(30):
                won = game_number < 27
                for at_bat in (1, 2):
                    row = {
                        "game_pk": f"game-{game_number}", "at_bat_index": at_bat,
                        "game_date": "2025-06-01", "inning": 7, "inning_half": "top", "outs": 1,
                        "leader_is_home": True, "lead_runs": 3, "away_runs": 1, "home_runs": 4,
                        "leader_won": won,
                    }
                    store.record_mlb_historical_state(row, self._stamp(f"{game_number}-{at_bat}"))
            model = EmpiricalMLBModel.fit(store.path, "2025-06-01", minimum_games=30)
            probability = model.probability(7, "top", True, 3)
            self.assertIsNotNone(probability)
            assert probability is not None
            # 27/30 wins, but the conservative Wilson bound must be lower.
            self.assertLess(probability, 0.9)
            bucket = next(iter(model.report()["eligible_buckets"].values()))
            self.assertEqual(bucket["games"], 30)
            self.assertEqual(bucket["wins"], 27)

    def test_sparse_bucket_cannot_emit_probability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            row = {
                "game_pk": "only-game", "at_bat_index": 1,
                "game_date": "2025-06-01", "inning": 8, "inning_half": "bottom", "outs": 2,
                "leader_is_home": False, "lead_runs": 4, "away_runs": 5, "home_runs": 1,
                "leader_won": True,
            }
            store.record_mlb_historical_state(row, self._stamp("single"))
            model = EmpiricalMLBModel.fit(store.path, "2025-06-01", minimum_games=30)
            self.assertIsNone(model.probability(8, "bottom", False, 4))


if __name__ == "__main__":
    unittest.main()
