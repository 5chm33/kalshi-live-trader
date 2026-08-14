from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.explore_mlb_quote_buckets import explore
from research.store import ResearchStore


class MLBQuoteExplorationTests(unittest.TestCase):
    def test_report_is_explicitly_exploratory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            now = datetime.now(timezone.utc)
            ticker = "KXMLBGAME-26JUN131605SEAWSH-WSH"
            store.record_historical_market({
                "ticker": ticker, "event_ticker": "KXMLBGAME-26JUN131605SEAWSH",
                "series_ticker": "KXMLBGAME", "notional_value_dollars": "1.0000",
            }, now)
            # Quote-study records can be grouped without any live execution path.
            for index in range(3):
                store.record_mlb_quote_study({
                    "game_pk": f"g{index}", "at_bat_index": 1, "ticker": ticker,
                    "state_source_at": f"2026-06-13T20:0{index}:00+00:00",
                    "candle_end_period_ts": 1781371260 + index,
                    "quote_delay_seconds": 60.0, "yes_bid_close": "0.70", "yes_ask_close": "0.72",
                    "leader_won": True, "mapping_method": "test",
                }, now)
                with store.connect() as conn:
                    conn.execute(
                        """INSERT INTO mlb_historical_states(
                            game_pk, at_bat_index, game_date, inning, inning_half, outs,
                            leader_is_home, lead_runs, away_runs, home_runs, away_team, home_team,
                            leader_won, source, source_at, received_at, payload_sha256, raw_json
                        ) VALUES (?, 1, '2026-06-13', 7, 'top', 1, 1, 3, 1, 4, 'Seattle Mariners',
                                  'Washington Nationals', 1, 'test', ?, ?, 'test', '{}')""",
                        (f"g{index}", f"2026-06-13T20:0{index}:00+00:00", now.isoformat()),
                    )
            report = explore(store.path, minimum_rows=3)
            self.assertEqual(report["status"], "exploratory_only_not_a_strategy")
            self.assertEqual(len(report["eligible_buckets"]), 1)
            self.assertEqual(report["eligible_buckets"][0]["status"], "exploratory_requires_unseen_holdout_validation")


if __name__ == "__main__":
    unittest.main()
