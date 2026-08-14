from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.mlb_quote_study import build_quote_study
from research.models import SourceStamp, payload_hash
from research.store import ResearchStore


class MLBQuoteStudyTests(unittest.TestCase):
    def _stamp(self, key: str) -> SourceStamp:
        return SourceStamp("test", datetime.now(timezone.utc), datetime(2026, 6, 13, 20, 0, 15, tzinfo=timezone.utc), payload_hash({"key": key}))

    def _build_store(self) -> ResearchStore:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = ResearchStore(Path(temp.name) / "research.sqlite3")
        state = {
            "game_pk": "g1", "at_bat_index": 1, "game_date": "2026-06-13", "inning": 7,
            "inning_half": "top", "outs": 1, "leader_is_home": True, "lead_runs": 3,
            "away_runs": 1, "home_runs": 4, "away_team": "Seattle Mariners", "home_team": "Washington Nationals",
            "leader_won": True,
        }
        store.record_mlb_historical_state(state, self._stamp("state"))
        market = {
            "ticker": "KXMLBGAME-26JUN131605SEAWSH-WSH", "event_ticker": "KXMLBGAME-26JUN131605SEAWSH",
            "series_ticker": "KXMLBGAME", "yes_sub_title": "Washington", "no_sub_title": "Seattle",
            "open_time": "2026-06-13T15:00:00Z", "close_time": "2026-06-13T23:10:00Z", "result": "yes",
        }
        store.record_historical_market(market, datetime.now(timezone.utc))
        store.record_historical_candles(market["ticker"], [{
            "end_period_ts": int(datetime(2026, 6, 13, 20, 1, 0, tzinfo=timezone.utc).timestamp()),
            "yes_bid": {"close_dollars": "0.70"}, "yes_ask": {"close_dollars": "0.72"},
            "price": {"close_dollars": "0.71"}, "volume_fp": "2.00", "open_interest_fp": "8.00",
        }], datetime.now(timezone.utc))
        return store

    def test_exact_team_date_mapping_records_first_post_state_quote(self) -> None:
        store = self._build_store()
        result = build_quote_study(store.path, 120)
        self.assertEqual(result["quote_study_rows_written"], 1)
        with store.connect() as conn:
            row = conn.execute("SELECT ticker, yes_ask_close, leader_won FROM mlb_quote_study").fetchone()
        self.assertEqual(row["ticker"], "KXMLBGAME-26JUN131605SEAWSH-WSH")
        self.assertEqual(row["yes_ask_close"], "0.72")
        self.assertEqual(row["leader_won"], 1)

    def test_quote_beyond_delay_window_is_rejected(self) -> None:
        store = self._build_store()
        result = build_quote_study(store.path, 20)
        self.assertEqual(result["quote_study_rows_written"], 0)
        self.assertEqual(result["states_without_post_state_quote"], 1)


if __name__ == "__main__":
    unittest.main()
