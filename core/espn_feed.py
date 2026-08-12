"""
ESPN Live Score Feed — v10
===========================
Polls ESPN's free API every 10 seconds for live game scores.
Detects score changes and emits events for the trading engine.
"""

import time
import logging
import requests
from typing import List, Dict, Optional
from dataclasses import dataclass, field

log = logging.getLogger('KALSHI')


@dataclass
class GameState:
    """Live game state from ESPN."""
    sport: str
    game_id: str
    team_a: str          # Away team abbreviation
    team_b: str          # Home team abbreviation
    team_a_full: str     # Full name
    team_b_full: str     # Full name
    score_a: int
    score_b: int
    state: str           # 'pre', 'in', 'post'
    period: int = 0      # Inning (baseball) or quarter/half
    period_half: str = ''  # 'top'/'bottom' for baseball
    clock: str = ''
    # Derived
    lead: int = 0
    leader: str = ''

    def __post_init__(self):
        self.lead = self.score_a - self.score_b
        if self.lead > 0:
            self.leader = self.team_a
        elif self.lead < 0:
            self.leader = self.team_b
        else:
            self.leader = ''


@dataclass
class ScoreChange:
    """Represents a detected score change."""
    game_id: str
    sport: str
    team_a: str
    team_b: str
    old_score_a: int
    old_score_b: int
    new_score_a: int
    new_score_b: int
    new_period: int
    new_lead: int
    new_leader: str
    timestamp: float = field(default_factory=time.time)


class ESPNFeed:
    """Polls ESPN for live scores and detects changes."""

    URLS = {
        'mlb': 'https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard',
        'nba': 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard',
        'nhl': 'https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard',
        'atp': 'https://site.api.espn.com/apis/site/v2/sports/tennis/atp/scoreboard',
        'wta': 'https://site.api.espn.com/apis/site/v2/sports/tennis/wta/scoreboard',
        'mls': 'https://site.api.espn.com/apis/site/v2/sports/soccer/usa.1/scoreboard',
        'epl': 'https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard',
    }

    def __init__(self, sports: List[str] = None):
        self.sports = sports or ['mlb', 'nba', 'atp', 'wta']
        self._prev_states: Dict[str, GameState] = {}
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = 8  # seconds

    def poll(self) -> tuple:
        """
        Poll all configured sports.
        Returns (all_games, score_changes).
        """
        all_games: List[GameState] = []
        changes: List[ScoreChange] = []

        for sport in self.sports:
            url = self.URLS.get(sport)
            if not url:
                continue
            games = self._fetch(url, sport)
            for g in games:
                if g.state != 'in':
                    continue
                all_games.append(g)

                # Detect score changes
                prev = self._prev_states.get(g.game_id)
                if prev and (prev.score_a != g.score_a or prev.score_b != g.score_b):
                    changes.append(ScoreChange(
                        game_id=g.game_id,
                        sport=g.sport,
                        team_a=g.team_a,
                        team_b=g.team_b,
                        old_score_a=prev.score_a,
                        old_score_b=prev.score_b,
                        new_score_a=g.score_a,
                        new_score_b=g.score_b,
                        new_period=g.period,
                        new_lead=g.lead,
                        new_leader=g.leader,
                    ))
                self._prev_states[g.game_id] = g

        return all_games, changes

    def _fetch(self, url: str, sport: str) -> List[GameState]:
        # Cache check
        now = time.time()
        if url in self._cache:
            data, ts = self._cache[url]
            if now - ts < self._cache_ttl:
                return data

        try:
            r = requests.get(url, timeout=8)
            if r.status_code != 200:
                return self._cache.get(url, ([], 0))[0]

            events = r.json().get('events', [])
            games = []

            for ev in events:
                try:
                    comp = ev.get('competitions', [{}])[0]
                    competitors = comp.get('competitors', [])
                    status = ev.get('status', {})
                    situation = comp.get('situation', {})

                    if len(competitors) < 2:
                        continue

                    away = next((c for c in competitors
                                 if c.get('homeAway') == 'away'), competitors[0])
                    home = next((c for c in competitors
                                 if c.get('homeAway') == 'home'), competitors[1])

                    def abbr(c):
                        if sport in ('atp', 'wta'):
                            name = c.get('athlete', c.get('team', {})).get('displayName', '')
                            parts = name.strip().split()
                            return parts[-1].upper() if parts else '?'
                        return c.get('team', {}).get('abbreviation', '?').upper()

                    def full_name(c):
                        if sport in ('atp', 'wta'):
                            return c.get('athlete', c.get('team', {})).get('displayName', '?')
                        return c.get('team', {}).get('displayName', '?')

                    def score(c):
                        try:
                            return int(c.get('score', '0') or '0')
                        except (ValueError, TypeError):
                            return 0

                    state_type = status.get('type', {}).get('state', 'pre')
                    period = situation.get('inning', status.get('period', 0)) or 0
                    period_half = (situation.get('inningHalf', '') or '').lower()

                    games.append(GameState(
                        sport=sport,
                        game_id=ev.get('id', ''),
                        team_a=abbr(away),
                        team_b=abbr(home),
                        team_a_full=full_name(away),
                        team_b_full=full_name(home),
                        score_a=score(away),
                        score_b=score(home),
                        state=state_type,
                        period=period,
                        period_half=period_half,
                        clock=status.get('displayClock', ''),
                    ))
                except Exception:
                    continue

            self._cache[url] = (games, now)
            return games

        except Exception as e:
            log.debug(f"[ESPN] {sport} error: {e}")
            return self._cache.get(url, ([], 0))[0]
