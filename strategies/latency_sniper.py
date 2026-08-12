"""
Latency Sniper Strategy — v10
==============================
The primary profit engine. Exploits the time gap between ESPN score
updates and Kalshi price adjustments.

How it works:
1. ESPN reports a score change (e.g., Team A scores a run)
2. We immediately calculate the new fair value based on game state
3. If Kalshi's price hasn't moved yet (stale), we buy at the old price
4. When market makers reprice (usually 5-30 seconds later), we profit

This is the same strategy used by HFT firms in traditional markets:
faster information → trade before the market adjusts → profit.

Win probability tables from Fangraphs/Baseball Reference/ATP stats.
"""

import time
import logging
from typing import Optional
from dataclasses import dataclass

log = logging.getLogger('KALSHI')


# ── Baseball Win Probability by (lead, inning) ──────────────────────────────
# Source: Fangraphs Win Expectancy tables (2015-2024 data)
MLB_WIN_PROB = {
    # (abs_lead, inning) -> probability leader wins
    (1, 1): 0.56, (1, 2): 0.58, (1, 3): 0.60, (1, 4): 0.63,
    (1, 5): 0.66, (1, 6): 0.70, (1, 7): 0.75, (1, 8): 0.81, (1, 9): 0.87,
    (2, 1): 0.63, (2, 2): 0.66, (2, 3): 0.69, (2, 4): 0.73,
    (2, 5): 0.77, (2, 6): 0.81, (2, 7): 0.86, (2, 8): 0.91, (2, 9): 0.95,
    (3, 1): 0.72, (3, 2): 0.75, (3, 3): 0.78, (3, 4): 0.81,
    (3, 5): 0.85, (3, 6): 0.88, (3, 7): 0.93, (3, 8): 0.96, (3, 9): 0.98,
    (4, 1): 0.79, (4, 2): 0.82, (4, 3): 0.85, (4, 4): 0.88,
    (4, 5): 0.91, (4, 6): 0.93, (4, 7): 0.96, (4, 8): 0.98, (4, 9): 0.99,
    (5, 1): 0.85, (5, 2): 0.87, (5, 3): 0.90, (5, 4): 0.92,
    (5, 5): 0.94, (5, 6): 0.96, (5, 7): 0.98, (5, 8): 0.99, (5, 9): 0.99,
    (6, 1): 0.89, (6, 2): 0.91, (6, 3): 0.93, (6, 4): 0.95,
    (6, 5): 0.96, (6, 6): 0.97, (6, 7): 0.99, (6, 8): 0.99, (6, 9): 0.99,
}


def mlb_win_prob(lead: int, inning: int) -> float:
    """Get win probability for the leading team."""
    if lead == 0:
        return 0.50
    abs_lead = min(abs(lead), 6)
    inn = max(1, min(inning, 9))
    return MLB_WIN_PROB.get((abs_lead, inn), 0.95 if abs_lead >= 4 else 0.70)


@dataclass
class SniperSignal:
    """A signal from the latency sniper."""
    ticker: str
    side: str            # 'bid' (buy YES) or 'ask' (buy NO)
    price: float         # Price in dollars to pay
    fair_value: float    # Our estimated fair value
    edge: float          # fair_value - price (for bid) or price - fair_value (for ask)
    contracts: float     # How many to buy
    reason: str
    sport: str
    urgency: str = 'high'  # 'high' = IOC, 'medium' = limit


class LatencySniper:
    """Detects and trades stale prices after score changes."""

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.min_edge = cfg.get('min_edge', 0.06)       # 6% minimum edge
        self.max_price = cfg.get('max_price', 0.92)     # Don't pay more than 92c
        self.min_price = cfg.get('min_price', 0.03)     # Don't buy below 3c
        self.stale_window = cfg.get('stale_window', 45) # Seconds after score change to consider stale
        self._recent_changes: dict = {}  # game_id -> (change, timestamp)
        self._traded: set = set()  # game_ids already traded this score change

    def on_score_change(self, change):
        """Record a score change for potential sniping."""
        self._recent_changes[change.game_id] = (change, time.time())
        log.info(f"[SNIPER] Score change: {change.team_a} {change.new_score_a} - "
                 f"{change.team_b} {change.new_score_b} (Period {change.new_period})")

    def evaluate(self, matched_game) -> Optional[SniperSignal]:
        """
        Check if a matched game has a stale price we can snipe.
        Called every scan cycle for all matched games.
        """
        gid = matched_game.game_id

        # Strategy 1: Post-score-change sniping (HIGHEST PRIORITY)
        if gid in self._recent_changes and gid not in self._traded:
            change, change_time = self._recent_changes[gid]
            age = time.time() - change_time

            if age < self.stale_window:
                signal = self._evaluate_score_change(matched_game, change)
                if signal:
                    self._traded.add(gid)
                    return signal

        # Strategy 2: Late-game value (slower edge, always active)
        signal = self._evaluate_late_game(matched_game)
        if signal:
            return signal

        return None

    def _evaluate_score_change(self, game, change) -> Optional[SniperSignal]:
        """Evaluate a game immediately after a score change."""
        if game.sport not in ('mlb', 'nba'):
            return None

        if game.sport == 'mlb':
            return self._snipe_mlb(game, change)

        return None

    def _snipe_mlb(self, game, change) -> Optional[SniperSignal]:
        """Snipe a baseball game after a score change."""
        lead = abs(game.lead)
        if lead == 0:
            return None  # Tied games are 50/50, no edge

        inning = game.period
        if inning < 1:
            return None

        fair_value = mlb_win_prob(lead, inning)
        if fair_value < 0.55:
            return None  # Not enough edge even theoretically

        # Determine which market to buy
        if game.leader == game.team_a:
            market = game.market_a
        elif game.leader == game.team_b:
            market = game.market_b
        else:
            return None

        if not market:
            return None

        # Check if price is stale (below our fair value)
        ask_price = market.yes_ask
        if ask_price <= 0 or ask_price > self.max_price:
            return None

        edge = fair_value - ask_price
        if edge < self.min_edge:
            return None

        # Calculate position size (edge-weighted)
        # Higher edge = more contracts, but cap at reasonable level
        contracts = 1.0
        if edge > 0.15:
            contracts = 2.0
        if edge > 0.25:
            contracts = 3.0

        reason = (f"SNIPE: {game.leader} leads {lead}-0 in inning {inning}. "
                  f"Fair: {fair_value:.0%}, Market: {ask_price:.0%}, Edge: {edge:.0%}")

        log.info(f"[SNIPER] ⚡ {reason}")

        return SniperSignal(
            ticker=market.ticker,
            side='bid',  # Buy YES on the leader
            price=ask_price,
            fair_value=fair_value,
            edge=edge,
            contracts=contracts,
            reason=reason,
            sport=game.sport,
            urgency='high',  # Use IOC for immediate fill
        )

    def _evaluate_late_game(self, game) -> Optional[SniperSignal]:
        """Evaluate late-game situations (slower edge, always running)."""
        if game.sport == 'mlb':
            return self._late_game_mlb(game)
        return None

    def _late_game_mlb(self, game) -> Optional[SniperSignal]:
        """Baseball late lead strategy — buy leader when up 3+ in 6th+."""
        lead = abs(game.lead)
        inning = game.period

        # Only late-game situations with clear leads
        if inning < 6 or lead < 3:
            return None

        # Don't re-trade games we already sniped
        if game.game_id in self._traded:
            return None

        fair_value = mlb_win_prob(lead, inning)

        # Get leader's market
        if game.leader == game.team_a:
            market = game.market_a
        elif game.leader == game.team_b:
            market = game.market_b
        else:
            return None

        if not market:
            return None

        ask_price = market.yes_ask
        if ask_price <= 0 or ask_price > self.max_price:
            return None

        edge = fair_value - ask_price
        if edge < self.min_edge:
            return None

        contracts = 1.0
        if edge > 0.12:
            contracts = 2.0

        reason = (f"LATE LEAD: {game.leader} +{lead} in inning {inning}. "
                  f"Fair: {fair_value:.0%}, Market: {ask_price:.0%}, Edge: {edge:.0%}")

        log.info(f"[SNIPER] 🎯 {reason}")

        self._traded.add(game.game_id)

        return SniperSignal(
            ticker=market.ticker,
            side='bid',
            price=ask_price,
            fair_value=fair_value,
            edge=edge,
            contracts=contracts,
            reason=reason,
            sport=game.sport,
            urgency='medium',  # Limit order OK for slower edge
        )

    def cleanup(self):
        """Remove old score changes (>5 min old)."""
        now = time.time()
        expired = [gid for gid, (_, ts) in self._recent_changes.items()
                   if now - ts > 300]
        for gid in expired:
            del self._recent_changes[gid]
            self._traded.discard(gid)
