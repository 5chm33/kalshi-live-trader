"""
Position Manager — v10
=======================
Tracks open positions, monitors P&L, and executes exits.
Uses the V2 API for fast IOC exits when needed.
"""

import time
import logging
from typing import Dict, Optional, List
from dataclasses import dataclass, field

log = logging.getLogger('KALSHI')


@dataclass
class Position:
    """An open position."""
    ticker: str
    side: str           # 'yes' or 'no'
    entry_price: float  # Dollars
    contracts: float
    strategy: str
    sport: str
    entry_time: float = field(default_factory=time.time)
    peak_price: float = 0.0
    order_id: str = ''

    def __post_init__(self):
        if self.peak_price == 0.0:
            self.peak_price = self.entry_price

    def cost(self) -> float:
        return self.entry_price * self.contracts

    def pnl_pct(self, current: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        return (current - self.entry_price) / self.entry_price

    def age_minutes(self) -> float:
        return (time.time() - self.entry_time) / 60.0


class PositionManager:
    """Manages positions with profit targets, stops, and trailing stops."""

    def __init__(self, client, config: dict = None):
        self.client = client
        cfg = config or {}

        # Exit parameters
        self.profit_target = cfg.get('profit_target', 0.90)    # Sell at 90c
        self.stop_loss_pct = cfg.get('stop_loss_pct', -0.35)   # -35% stop
        self.trail_pct = cfg.get('trail_pct', 0.20)            # 20% trail from peak
        self.max_hold_minutes = cfg.get('max_hold_min', 120)   # 2 hour max hold

        # State
        self.positions: Dict[str, Position] = {}
        self.blacklist: set = set()
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.realized_pnl = 0.0

    def open_position(self, ticker: str, side: str, entry_price: float,
                      contracts: float, strategy: str, sport: str,
                      order_id: str = ''):
        """Record a new open position."""
        self.positions[ticker] = Position(
            ticker=ticker, side=side, entry_price=entry_price,
            contracts=contracts, strategy=strategy, sport=sport,
            order_id=order_id,
        )
        self.total_trades += 1
        log.info(f"[POS] Opened: {side.upper()} {ticker} x{contracts:.2f} @ ${entry_price:.4f}")

    def check_exits(self):
        """Check all positions for exit conditions."""
        if not self.positions:
            return

        to_exit = []

        for ticker, pos in list(self.positions.items()):
            if ticker in self.blacklist:
                to_exit.append((ticker, 'blacklisted'))
                continue

            # Get current price
            market = self.client.get_market(ticker)
            if not market:
                continue

            # Current bid (what we can sell for)
            if pos.side == 'yes':
                current = self._to_dollars(market.get('yes_bid_dollars'))
            else:
                current = self._to_dollars(market.get('no_bid_dollars'))

            if current <= 0:
                continue

            # Update peak
            if current > pos.peak_price:
                pos.peak_price = current

            pnl = pos.pnl_pct(current)
            age = pos.age_minutes()

            # 1. Profit target (price >= 90c)
            if current >= self.profit_target:
                to_exit.append((ticker, f'profit_target ({current:.2f})'))
                continue

            # 2. Hard stop loss
            if pnl <= self.stop_loss_pct:
                to_exit.append((ticker, f'stop_loss ({pnl:.0%})'))
                continue

            # 3. Trailing stop (only if in profit)
            if pos.peak_price > pos.entry_price * 1.05:  # At least 5% up
                drop = (pos.peak_price - current) / pos.peak_price
                if drop >= self.trail_pct:
                    to_exit.append((ticker, f'trailing_stop (peak={pos.peak_price:.2f}, now={current:.2f})'))
                    continue

            # 4. Time-based exit (held too long)
            if age > self.max_hold_minutes and abs(pnl) < 0.05:
                to_exit.append((ticker, f'time_exit ({age:.0f}min, flat)'))
                continue

        # Execute exits
        for ticker, reason in to_exit:
            self._exit(ticker, reason)

    def _exit(self, ticker: str, reason: str):
        """Execute an exit order."""
        pos = self.positions.get(ticker)
        if not pos:
            return

        # Get current bid for sell price
        market = self.client.get_market(ticker)
        if market:
            if pos.side == 'yes':
                sell_price = self._to_dollars(market.get('yes_bid_dollars'))
            else:
                sell_price = self._to_dollars(market.get('no_bid_dollars'))
        else:
            sell_price = max(0.01, pos.entry_price - 0.05)

        if sell_price <= 0:
            sell_price = 0.01

        log.info(f"[POS] EXIT ({reason}): SELL {pos.side.upper()} {ticker} "
                 f"x{pos.contracts:.2f} @ ${sell_price:.4f}")

        # Use IOC to sell immediately at bid
        # In V2: selling YES = placing an 'ask' at the current bid price
        v2_side = 'ask' if pos.side == 'yes' else 'bid'
        result = self.client.place_ioc(ticker, v2_side, pos.contracts, sell_price)

        if result and result.get('order_id'):
            filled = float(result.get('fill_count', '0'))
            if filled > 0:
                avg = float(result.get('average_fill_price', str(sell_price)))
                pnl = (avg - pos.entry_price) * filled
                self.realized_pnl += pnl
                if pnl >= 0:
                    self.wins += 1
                else:
                    self.losses += 1
                log.info(f"[POS] ✓ Sold {filled:.2f} @ ${avg:.4f} | "
                         f"P&L: ${pnl:+.4f}")
            else:
                log.warning(f"[POS] IOC exit got 0 fills for {ticker}")
                # Try V1 as fallback
                self._exit_v1(pos, sell_price)
        elif result and result.get('_code') == 409:
            log.warning(f"[POS] Market not active: {ticker} — removing")
            self.blacklist.add(ticker)
        else:
            # Fallback to V1
            self._exit_v1(pos, sell_price)

        # Remove position regardless
        if ticker in self.positions:
            del self.positions[ticker]

    def _exit_v1(self, pos: Position, price: float):
        """Fallback exit using V1 API."""
        price_cents = max(1, int(round(price * 100)))
        result = self.client.place_order_v1(
            pos.ticker, pos.side, 'sell',
            int(pos.contracts), price_cents
        )
        if result:
            log.info(f"[POS] V1 exit placed for {pos.ticker}")

    def _to_dollars(self, val) -> float:
        if val is None:
            return 0.0
        try:
            f = float(val)
            return f if f <= 1.0 else f / 100.0
        except (ValueError, TypeError):
            return 0.0

    def get_exposure(self) -> float:
        """Total dollars at risk."""
        return sum(p.cost() for p in self.positions.values())

    def get_stats(self) -> dict:
        wr = self.wins / max(self.total_trades, 1)
        return {
            'positions': len(self.positions),
            'trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': wr,
            'realized_pnl': self.realized_pnl,
        }
