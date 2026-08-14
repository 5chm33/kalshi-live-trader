"""Historical MLB state collector for calibration research.

Completed MLB game feeds provide pre-resolution state/outcome pairs. The
collector records plate-appearance states without generating probabilities,
orders, or paper fills. Statistical evaluation must cluster by game; repeated
states within a game are not independent observations.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from typing import Any, Mapping

import requests

from research.models import SourceStamp, payload_hash
from research.store import ResearchStore

SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule/games/"
GAME_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"


class MLBHistoricalCollector:
    def __init__(self, store: ResearchStore, session: requests.Session | None = None):
        self.store = store
        self.session = session or requests.Session()

    def game_ids(self, target_date: date) -> list[str]:
        response = self.session.get(
            SCHEDULE_URL,
            params={"sportId": 1, "date": target_date.isoformat(), "gameType": "R"},
            timeout=20,
        )
        response.raise_for_status()
        return [
            str(game["gamePk"])
            for day in response.json().get("dates", [])
            for game in day.get("games", [])
            if game.get("gamePk") and str(game.get("status", {}).get("abstractGameState", "")) == "Final"
        ]

    @staticmethod
    def _parse_time(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _game_records(self, game_pk: str, game_date: date) -> list[tuple[Mapping[str, Any], SourceStamp]]:
        # Use a per-call public request in worker threads. Ledger writes remain
        # serial in the caller, avoiding SQLite cross-thread mutation.
        response = requests.get(GAME_FEED_URL.format(game_pk=game_pk), timeout=30)
        response.raise_for_status()
        payload = response.json()
        linescore = payload.get("liveData", {}).get("linescore", {}).get("teams", {})
        final_away = int(linescore.get("away", {}).get("runs", 0) or 0)
        final_home = int(linescore.get("home", {}).get("runs", 0) or 0)
        if final_home == final_away:
            # MLB regular-season games do not resolve tied; avoid a malformed
            # or suspended feed from contaminating binary win outcomes.
            return []
        teams = payload.get("gameData", {}).get("teams", {})
        away_team = str(teams.get("away", {}).get("name", ""))
        home_team = str(teams.get("home", {}).get("name", ""))
        if not away_team or not home_team:
            return []
        plays = payload.get("liveData", {}).get("plays", {}).get("allPlays", [])
        records: list[tuple[Mapping[str, Any], SourceStamp]] = []
        for play in plays:
            about = play.get("about", {}) if isinstance(play.get("about"), Mapping) else {}
            result = play.get("result", {}) if isinstance(play.get("result"), Mapping) else {}
            count = play.get("count", {}) if isinstance(play.get("count"), Mapping) else {}
            inning = about.get("inning")
            half = str(about.get("halfInning", "")).lower()
            away = result.get("awayScore")
            home = result.get("homeScore")
            index = about.get("atBatIndex")
            if not isinstance(inning, int) or half not in {"top", "bottom"}:
                continue
            if not isinstance(away, int) or not isinstance(home, int) or not isinstance(index, int):
                continue
            lead = abs(home - away)
            if inning < 6 or lead < 3:
                continue
            leader_is_home = home > away
            source_at = self._parse_time(about.get("endTime"))
            raw = {
                "game_pk": str(game_pk), "at_bat_index": index, "game_date": game_date.isoformat(),
                "inning": inning, "inning_half": half, "outs": count.get("outs"),
                "leader_is_home": leader_is_home, "lead_runs": lead,
                "away_runs": away, "home_runs": home,
                "away_team": away_team, "home_team": home_team,
                "leader_won": (final_home > final_away) if leader_is_home else (final_away > final_home),
            }
            stamp = SourceStamp(
                source="mlb_stats_api_completed_game",
                source_at=source_at,
                received_at=datetime.now(timezone.utc),
                payload_sha256=payload_hash(raw),
            )
            records.append((raw, stamp))
        return records

    def collect_game(self, game_pk: str, game_date: date) -> int:
        records = self._game_records(game_pk, game_date)
        self.store.record_mlb_historical_states(records)
        return len(records)

    def collect_date(self, target_date: date, max_games: int | None = None, workers: int = 4) -> dict[str, int]:
        ids = self.game_ids(target_date)
        if max_games is not None:
            ids = ids[:max_games]
        if workers <= 0:
            raise ValueError("workers must be positive")
        states = 0
        # Bounded public GET concurrency significantly shortens backfills while
        # retaining serial database commits and deterministic durable records.
        with ThreadPoolExecutor(max_workers=min(workers, len(ids) or 1)) as executor:
            futures = {executor.submit(self._game_records, game_pk, target_date): game_pk for game_pk in ids}
            for future in as_completed(futures):
                records = future.result()
                self.store.record_mlb_historical_states(records)
                states += len(records)
        return {"date": target_date.isoformat(), "games": len(ids), "states_seen": states, "stored_total": self.store.historical_mlb_state_count()}
