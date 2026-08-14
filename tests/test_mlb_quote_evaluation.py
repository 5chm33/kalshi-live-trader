from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.evaluate_mlb_quote_study import evaluate_quote_study
from research.store import ResearchStore


class MLBQuoteEvaluationTests(unittest.TestCase):
    def test_quote_evaluation_is_explicitly_non_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            market = {
                "ticker": "KXMLBGAME-26JUN131605SEAWSH-WSH",
                "event_ticker": "KXMLBGAME-26JUN131605SEAWSH",
                "series_ticker": "KXMLBGAME", "notional_value_dollars": "1.0000",
            }
            now = datetime.now(timezone.utc)
            store.record_historical_market(market, now)
            store.record_mlb_quote_study({
                "game_pk": "g1", "at_bat_index": 1, "ticker": market["ticker"],
                "state_source_at": "2026-06-13T20:00:00+00:00", "candle_end_period_ts": 1781371260,
                "quote_delay_seconds": 60.0, "yes_bid_close": "0.70", "yes_ask_close": "0.72",
                "leader_won": True, "mapping_method": "test",
            }, now)
            report = evaluate_quote_study(store.path)
            self.assertEqual(report["status"], "quote_only_retrospective_not_execution_proof")
            self.assertEqual(report["aligned_rows"], 1)
            self.assertEqual(report["execution_claim"], "none; historical candles do not prove fillable depth")


if __name__ == "__main__":
    unittest.main()
