"""
Tennis Value Strategy — v10
============================
Two sub-strategies for tennis markets:

1. VOLATILITY: When a higher-ranked player loses the first set, the market
   overreacts. ATP/WTA data shows they still win 62-70% of the time.
   Buy their YES when it drops below fair value.

2. RANKINGS EDGE: When ESPN rankings show a large rank gap but the market
   hasn't fully priced it in, buy the favorite.

Uses ESPN ATP/WTA rankings + live match scores.
"""

import time
import logging
import requests
from typing import Optional, Dict, List
from dataclasses import dataclass

log = logging.getLogger('KALSHI')

# Win probability for higher-ranked player when down 0-1 in sets
COMEBACK_PROB = {
    (0, 20): 0.55,
    (20, 50): 0.62,
    (50, 100): 0.67,
    (100, 500): 0.70,
}

# Win probability based on rank difference (pre-match / general)
RANK_WIN_PROB = {
    (0, 10): 0.58,
    (10, 25): 0.63,
    (25, 50): 0.68,
    (50, 100): 0.73,
    (100, 200): 0.78,
    (200, 500): 0.83,
}


def get_comeback_prob(rank_diff: int) -> float:
    for (lo, hi), prob in COMEBACK_PROB.items():
        if lo <= rank_diff < hi:
            return prob
    return 0.62


def get_rank_win_prob(rank_diff: int) -> float:
    for (lo, hi), prob in RANK_WIN_PROB.items():
        if lo <= rank_diff < hi:
            return prob
    return 0.60


@dataclass
class TennisSignal:
    """Signal from tennis strategy."""
    ticker: str
    side: str           # 'bid' (buy YES)
    price: float        # Dollars
    fair_value: float
    edge: float
    contracts: float
    reason: str
    sport: str = 'tennis'
    urgency: str = 'medium'


class TennisValueStrategy:
    """Tennis value strategy using ESPN rankings."""

    ESPN_ATP = 'https://site.api.espn.com/apis/site/v2/sports/tennis/atp/rankings'
    ESPN_WTA = 'https://site.api.espn.com/apis/site/v2/sports/tennis/wta/rankings'

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.min_rank_diff = cfg.get('min_rank_diff', 25)
        self.min_edge = cfg.get('min_edge', 0.08)
        self.max_price = cfg.get('max_price', 0.65)
        self._rankings: Dict[str, int] = {}  # name -> rank
        self._rankings_ts = 0
        self._traded: set = set()

        log.info("[TENNIS] Value strategy initialized")

    def refresh_rankings(self):
        """Fetch ATP + WTA rankings from ESPN (every 6 hours)."""
        if time.time() - self._rankings_ts < 21600:
            return

        try:
            for url in (self.ESPN_ATP, self.ESPN_WTA):
                r = requests.get(url, timeout=10)
                if r.status_code != 200:
                    continue
                data = r.json()
                for ranking in data.get('rankings', []):
                    for entry in ranking.get('entries', [])[:100]:
                        athlete = entry.get('athlete', {})
                        name = athlete.get('displayName', '').upper()
                        rank = entry.get('rank', 0)
                        if name and rank > 0:
                            self._rankings[name] = rank
                            # Also store last name for matching
                            parts = name.split()
                            if parts:
                                self._rankings[parts[-1]] = rank

            self._rankings_ts = time.time()
            log.info(f"[TENNIS] Rankings loaded: {len(self._rankings)} players")
        except Exception as e:
            log.debug(f"[TENNIS] Rankings fetch error: {e}")

    def evaluate(self, matched_game) -> Optional[TennisSignal]:
        """Evaluate a matched tennis game for value."""
        if matched_game.sport not in ('atp', 'wta'):
            return None

        if matched_game.game_id in self._traded:
            return None

        self.refresh_rankings()

        # Get player rankings
        rank_a = self._get_rank(matched_game.team_a)
        rank_b = self._get_rank(matched_game.team_b)

        if rank_a <= 0 or rank_b <= 0:
            return None

        rank_diff = abs(rank_a - rank_b)
        if rank_diff < self.min_rank_diff:
            return None

        # Identify favorite (lower rank = better)
        if rank_a < rank_b:
            fav_team = matched_game.team_a
            fav_rank = rank_a
            fav_market = matched_game.market_a
            underdog_team = matched_game.team_b
        else:
            fav_team = matched_game.team_b
            fav_rank = rank_b
            fav_market = matched_game.market_b
            underdog_team = matched_game.team_a

        if not fav_market:
            return None

        ask_price = fav_market.yes_ask
        if ask_price <= 0 or ask_price > self.max_price:
            return None

        # Calculate fair value based on rankings
        fair_value = get_rank_win_prob(rank_diff)

        # If favorite is losing (score_a < score_b or vice versa), use comeback prob
        if matched_game.leader and matched_game.leader != fav_team:
            fair_value = get_comeback_prob(rank_diff)

        edge = fair_value - ask_price
        if edge < self.min_edge:
            return None

        contracts = 1.0
        if edge > 0.15:
            contracts = 2.0

        reason = (f"TENNIS: {fav_team} (rank #{fav_rank}) vs {underdog_team}. "
                  f"Rank diff: {rank_diff}. Fair: {fair_value:.0%}, "
                  f"Market: {ask_price:.0%}, Edge: {edge:.0%}")

        log.info(f"[TENNIS] 🎾 {reason}")

        self._traded.add(matched_game.game_id)

        return TennisSignal(
            ticker=fav_market.ticker,
            side='bid',
            price=ask_price,
            fair_value=fair_value,
            edge=edge,
            contracts=contracts,
            reason=reason,
        )

    def _get_rank(self, team_key: str) -> int:
        """Look up a player's rank by name/abbreviation."""
        key = team_key.upper()
        if key in self._rankings:
            return self._rankings[key]
        # Try partial match
        for name, rank in self._rankings.items():
            if key in name or name.startswith(key):
                return rank
        return 0
