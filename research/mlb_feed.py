"""MLB public live-state adapter for paper research.

The adapter captures data only; it makes no inference about market probability.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping

import requests

from research.models import GameState, SourceStamp, payload_hash

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule/games/"


class MLBFeed:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()

    @staticmethod
    def _parse_game(game: Mapping[str, Any], stamp: SourceStamp) -> GameState:
        teams = game.get("teams", {})
        away = teams.get("away", {}) if isinstance(teams, Mapping) else {}
        home = teams.get("home", {}) if isinstance(teams, Mapping) else {}
        linescore = game.get("linescore", {}) if isinstance(game.get("linescore"), Mapping) else {}
        score_teams = linescore.get("teams", {}) if isinstance(linescore, Mapping) else {}
        score_away = score_teams.get("away", {}) if isinstance(score_teams, Mapping) else {}
        score_home = score_teams.get("home", {}) if isinstance(score_teams, Mapping) else {}
        status = game.get("status", {}) if isinstance(game.get("status"), Mapping) else {}

        def name(side: Mapping[str, Any]) -> str:
            team = side.get("team", {}) if isinstance(side.get("team"), Mapping) else {}
            return str(team.get("name", ""))

        return GameState(
            source_game_id=str(game.get("gamePk", "")),
            league="MLB",
            status=str(status.get("abstractGameState", status.get("detailedState", "Unknown"))),
            away_team=name(away),
            home_team=name(home),
            away_runs=int(score_away.get("runs", 0) or 0),
            home_runs=int(score_home.get("runs", 0) or 0),
            inning=int(linescore["currentInning"]) if linescore.get("currentInning") is not None else None,
            inning_half=str(linescore.get("inningState", "")) or None,
            scheduled_innings=int(linescore["scheduledInnings"]) if linescore.get("scheduledInnings") is not None else None,
            stamp=stamp,
            raw=game,
        )

    def schedule(self, target_date: date | None = None) -> list[GameState]:
        """Return all games for a date with linescore hydration."""
        target = target_date or datetime.now(timezone.utc).date()
        response = self.session.get(
            MLB_SCHEDULE_URL,
            params={"sportId": 1, "date": target.isoformat(), "hydrate": "linescore,liveData"},
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        stamp = SourceStamp(
            source="mlb_stats_api",
            source_at=None,
            received_at=datetime.now(timezone.utc),
            payload_sha256=payload_hash(payload),
        )
        games: list[GameState] = []
        for day in payload.get("dates", []):
            for game in day.get("games", []):
                games.append(self._parse_game(game, stamp))
        return games

    def live_games(self, target_date: date | None = None) -> list[GameState]:
        active_states = {"Live", "In Progress", "Manager Challenge"}
        return [game for game in self.schedule(target_date) if game.status in active_states]
