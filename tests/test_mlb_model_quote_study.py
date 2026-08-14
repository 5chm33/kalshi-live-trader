from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.mlb_model_quote_study import evaluate_model_vs_quotes
from research.models import SourceStamp, payload_hash
from research.store import ResearchStore


class MLBModelQuoteStudyTests(unittest.TestCase):
    def _stamp(self, value: str, day: str) -> SourceStamp:
        return SourceStamp("test", datetime.now(timezone.utc), datetime.fromisoformat(day + "T20:00:00+00:00"), payload_hash({"value": value}))

    def _state(self, game: str, day: str, at_bat: int, won: bool) -> dict[str, object]:
        return {
            "game_pk": game, "at_bat_index": at_bat, "game_date": day, "inning": 7,
            "inning_half": "top", "outs": 1, "leader_is_home": True, "lead_runs": 3,
            "away_runs": 1, "home_runs": 4, "away_team": "Seattle Mariners",
            "home_team": "Washington Nationals", "leader_won": won,
        }

    def test_study_uses_prior_training_only_and_is_not_execution_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            # 30 independent training games: conservative bucket is eligible.
            for index in range(30):
                row = self._state(f"train-{index}", "2025-06-01", 1, index < 29)
                store.record_mlb_historical_state(row, self._stamp(f"train-{index}", "2025-06-01"))
            ticker = "KXMLBGAME-26JUN131605SEAWSH-WSH"
            store.record_historical_market({
                "ticker": ticker, "event_ticker": "KXMLBGAME-26JUN131605SEAWSH",
                "series_ticker": "KXMLBGAME", "notional_value_dollars": "1.0000",
            }, datetime.now(timezone.utc))
            test = self._state("test", "2026-06-13", 1, True)
            store.record_mlb_historical_state(test, self._stamp("test", "2026-06-13"))
            store.record_mlb_quote_study({
                "game_pk": "test", "at_bat_index": 1, "ticker": ticker,
                "state_source_at": "2026-06-13T20:00:00+00:00", "candle_end_period_ts": 1781371260,
                "quote_delay_seconds": 60.0, "yes_bid_close": "0.70", "yes_ask_close": "0.72",
                "leader_won": True, "mapping_method": "test",
            }, datetime.now(timezone.utc))
            report = evaluate_model_vs_quotes(
                store.path, "2025-12-31", "2026-01-01", "2026-12-31", minimum_games=30
            )
            self.assertEqual(report["status"], "out_of_sample_quote_only_not_execution_proof")
            self.assertEqual(report["selected_quote_proxy_candidates"], 1)
            self.assertEqual(report["execution_claim"], "none; archived candles do not prove fillable depth")


if __name__ == "__main__":
    unittest.main()
