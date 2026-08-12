"""
Kalshi Live Trader — v10 (Full SOTA)
======================================
Unified bot combining:
  1. Latency Sniper — ESPN score detection → stale price sniping (MLB, NBA)
  2. Weather Ensemble — 209-member forecast (ECMWF+AIFS+GFS+ICON+UKMO)
  3. Tennis Value — Rankings-based value + volatility after set loss

Architecture:
  - Fast loop (10s): ESPN poll + latency sniper + tennis
  - Slow loop (180s): Weather ensemble scan
  - Position manager: trailing stops, profit targets, time exits
  - V2 API: IOC orders for instant fills

Run: python3 main.py
"""

import os
import sys
import json
import time
import logging
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.kalshi_client import KalshiClient
from core.espn_feed import ESPNFeed
from core.market_matcher import MarketMatcher
from core.position_manager import PositionManager
from strategies.latency_sniper import LatencySniper
from strategies.tennis_value import TennisValueStrategy
from strategies.weather_ensemble import EnsembleWeatherEngine

# ── Logging ───────────────────────────────────────────────────────────────────
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-5s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/v10.log', encoding='utf-8'),
    ]
)
log = logging.getLogger('KALSHI')

# ── Config ────────────────────────────────────────────────────────────────────
SCAN_INTERVAL = 10       # Seconds between ESPN polls (fast loop)
WEATHER_INTERVAL = 180   # Seconds between weather scans (slow loop)
MONITOR_EVERY = 3        # Check exits every N fast scans
STATS_EVERY = 30         # Print stats every N fast scans
MAX_POSITIONS = 8        # Max concurrent positions
MAX_EXPOSURE_PCT = 0.50  # Max 50% of balance at risk
MAX_PER_TRADE_PCT = 0.20 # Max 20% of balance per trade

# Weather quality filters (from v7/v8)
MIN_EDGE_WEATHER = 0.12       # 12% min edge for above/below
MIN_EDGE_WEATHER_RANGE = 0.25 # 25% min edge for range markets
MIN_CONFIDENCE_WEATHER = 0.55 # 55% min confidence
MAX_NO_PRICE_RANGE = 0.45     # Don't pay more than 45c for NO on range

# Weather series to scan
WEATHER_SERIES = [
    'KXHIGHTNYC', 'KXHIGHTCHI', 'KXHIGHTLAX', 'KXHIGHTHOU', 'KXHIGHTPHX',
    'KXHIGHTDAL', 'KXHIGHTATL', 'KXHIGHTDC', 'KXHIGHTSEA', 'KXHIGHTDEN',
    'KXHIGHTMIA', 'KXHIGHTSF', 'KXHIGHTBOS', 'KXHIGHTDET', 'KXHIGHTMIN',
    'KXLOWTNYC', 'KXLOWTCHI', 'KXLOWTLAX', 'KXLOWTHOU', 'KXLOWTPHX',
    'KXLOWTDAL', 'KXLOWTATL', 'KXLOWTDC', 'KXLOWTSEA', 'KXLOWTDEN',
    'KXLOWTMIA', 'KXLOWTSF', 'KXLOWTBOS', 'KXLOWTDET', 'KXLOWTMIN',
    'KXHIGHTAUS', 'KXLOWTAUS',
]


def load_config() -> dict:
    for path in ('config.json', '../config.json'):
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    log.error("config.json not found!")
    sys.exit(1)


def banner():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           KALSHI LIVE TRADER v10 — FULL SOTA ENGINE             ║
╠══════════════════════════════════════════════════════════════════╣
║  [1] Latency Sniper  — ESPN scores → stale price sniping       ║
║  [2] Weather Ensemble — 209 members (ECMWF+AIFS+GFS+ICON+UKMO) ║
║  [3] Tennis Value     — Rankings + volatility after set loss    ║
║                                                                  ║
║  Fast loop: 10s (sports) | Slow loop: 180s (weather)            ║
║  Orders: V2 API with IOC | Exits: Trailing stop + targets       ║
╚══════════════════════════════════════════════════════════════════╝
""")


class LiveTrader:
    def __init__(self, config: dict):
        self.config = config
        self.scan_count = 0
        self.start_time = time.time()
        self._last_weather_scan = 0

        # Initialize components
        log.info("[INIT] Connecting to Kalshi...")
        self.client = KalshiClient(config)
        if not self.client.check_auth():
            raise RuntimeError("Auth failed! Check config.json")

        self.start_balance = self.client.get_balance()
        log.info(f"[INIT] Balance: ${self.start_balance:.2f}")

        # Sports strategies
        self.espn = ESPNFeed(sports=['mlb', 'nba', 'atp', 'wta'])
        self.matcher = MarketMatcher(self.client)
        self.sniper = LatencySniper(config.get('sniper', {}))
        self.tennis = TennisValueStrategy(config.get('tennis', {}))

        # Weather strategy
        self.weather = EnsembleWeatherEngine()

        # Position management
        self.positions = PositionManager(self.client, config.get('exits', {}))

        log.info("[INIT] All strategies loaded. Starting scan loop.")

    def run(self):
        """Main loop."""
        while True:
            try:
                self._cycle()
            except KeyboardInterrupt:
                log.info("[MAIN] Shutting down...")
                self._final_stats()
                break
            except Exception as e:
                log.error(f"[MAIN] Cycle error: {e}")
                log.debug(traceback.format_exc())
                time.sleep(SCAN_INTERVAL)

    def _cycle(self):
        self.scan_count += 1
        t0 = time.time()

        # ── 1. Monitor existing positions ─────────────────────────────────
        if self.scan_count % MONITOR_EVERY == 0:
            self.positions.check_exits()

        # ── 2. Poll ESPN for live scores (FAST) ───────────────────────────
        games, changes = self.espn.poll()

        # ── 3. Process score changes ──────────────────────────────────────
        for change in changes:
            self.sniper.on_score_change(change)
            log.info(f"[SCORE] {change.sport.upper()}: "
                     f"{change.team_a} {change.new_score_a} - "
                     f"{change.team_b} {change.new_score_b} "
                     f"(was {change.old_score_a}-{change.old_score_b})")

        # ── 4. Match games to Kalshi markets ──────────────────────────────
        balance = self.client.get_balance()
        signals = []

        if games:
            matched = self.matcher.match_games(games)

            # Evaluate latency sniper signals
            for game in matched:
                sig = self.sniper.evaluate(game)
                if sig:
                    signals.append(sig)

            # Evaluate tennis signals
            for game in matched:
                sig = self.tennis.evaluate(game)
                if sig:
                    signals.append(sig)

        # ── 5. Weather scan (SLOW — every 180s) ──────────────────────────
        if time.time() - self._last_weather_scan >= WEATHER_INTERVAL:
            self._last_weather_scan = time.time()
            weather_signals = self._scan_weather(balance)
            signals.extend(weather_signals)

        # ── 6. Execute signals ────────────────────────────────────────────
        signals_executed = 0
        for signal in signals:
            if len(self.positions.positions) >= MAX_POSITIONS:
                log.info(f"[RISK] Max positions ({MAX_POSITIONS}) reached")
                break

            exposure = self.positions.get_exposure()
            if balance > 0 and exposure / balance >= MAX_EXPOSURE_PCT:
                log.info(f"[RISK] Max exposure ({MAX_EXPOSURE_PCT:.0%}) reached")
                break

            # Size the trade
            max_cost = balance * MAX_PER_TRADE_PCT
            price = signal.price
            if price <= 0:
                continue
            max_contracts = max_cost / price
            contracts = min(signal.contracts, max_contracts)
            contracts = max(1.0, round(contracts, 2))

            total_cost = contracts * price
            if total_cost > balance:
                contracts = max(1.0, round(balance / price, 2))
                total_cost = contracts * price
            if total_cost > balance:
                continue

            # Execute
            urgency = getattr(signal, 'urgency', 'medium')
            if urgency == 'high':
                result = self.client.place_ioc(signal.ticker, signal.side, contracts, price)
            else:
                result = self.client.place_order_v2(signal.ticker, signal.side, contracts, price)

            if result and result.get('order_id'):
                filled = float(result.get('fill_count', '0'))
                if filled > 0:
                    avg_price = float(result.get('average_fill_price', str(price)))
                    pos_side = 'yes' if signal.side == 'bid' else 'no'
                    strategy = getattr(signal, 'sport', 'weather')
                    self.positions.open_position(
                        ticker=signal.ticker, side=pos_side,
                        entry_price=avg_price, contracts=filled,
                        strategy=strategy, sport=strategy,
                        order_id=result['order_id'],
                    )
                    balance -= filled * avg_price
                    signals_executed += 1
                    log.info(f"[TRADE] ✓ {signal.ticker} {filled:.2f}x @ ${avg_price:.4f} | "
                             f"Edge: {signal.edge:.0%} | {signal.reason[:60]}")

        # ── 7. Periodic stats ─────────────────────────────────────────────
        if self.scan_count % STATS_EVERY == 0:
            self._stats(balance)

        # Log summary (every minute or when signals found)
        if signals_executed > 0 or self.scan_count % 6 == 0:
            n_games = len(games) if games else 0
            log.info(f"[SCAN #{self.scan_count}] Games: {n_games} | "
                     f"Signals: {len(signals)} | Executed: {signals_executed} | "
                     f"Positions: {len(self.positions.positions)} | "
                     f"Balance: ${balance:.2f}")

        # Cleanup
        self.sniper.cleanup()

        # Sleep
        elapsed = time.time() - t0
        time.sleep(max(0, SCAN_INTERVAL - elapsed))

    def _scan_weather(self, balance: float) -> list:
        """Scan weather markets using the 209-member ensemble engine."""
        signals = []
        try:
            for series in WEATHER_SERIES:
                markets = self.client.get_markets(series_ticker=series, status='open', limit=50)
                if not markets:
                    continue

                for m in markets:
                    ticker = m.get('ticker', '')
                    yes_ask = self._to_dollars(m.get('yes_ask_dollars'))
                    no_ask = self._to_dollars(m.get('no_ask_dollars'))

                    if yes_ask <= 0 and no_ask <= 0:
                        continue

                    # Get floor/cap strike from market data
                    floor_strike = m.get('floor_strike')
                    cap_strike = m.get('cap_strike')

                    # Determine market type
                    if floor_strike and cap_strike:
                        mtype = 'range'
                    elif floor_strike:
                        mtype = 'above'
                    elif cap_strike:
                        mtype = 'below'
                    else:
                        continue

                    # Run ensemble analysis
                    try:
                        result = self.weather.analyze_market(
                            ticker=ticker,
                            market_type=mtype,
                            floor_strike=float(floor_strike) if floor_strike else None,
                            cap_strike=float(cap_strike) if cap_strike else None,
                        )
                    except Exception:
                        continue

                    if not result or 'probability' not in result:
                        continue

                    prob = result['probability']
                    confidence = result.get('confidence', 0.5)

                    # Quality filters
                    if confidence < MIN_CONFIDENCE_WEATHER:
                        continue

                    # Determine trade direction and edge
                    if mtype == 'range':
                        # Range: usually buy NO (bet it WON'T be in range)
                        if prob < 0.50 and no_ask > 0:
                            edge = (1 - prob) - no_ask
                            if edge < MIN_EDGE_WEATHER_RANGE:
                                continue
                            if no_ask > MAX_NO_PRICE_RANGE:
                                continue
                            signals.append(type('Sig', (), {
                                'ticker': ticker, 'side': 'ask',
                                'price': no_ask, 'edge': edge,
                                'contracts': 1.0, 'urgency': 'medium',
                                'reason': f"WEATHER RANGE: P(in)={prob:.0%}, NO@{no_ask:.2f}, edge={edge:.0%}",
                                'sport': 'weather',
                            })())
                    elif mtype == 'above':
                        if prob > 0.50 and yes_ask > 0:
                            edge = prob - yes_ask
                            if edge < MIN_EDGE_WEATHER:
                                continue
                            signals.append(type('Sig', (), {
                                'ticker': ticker, 'side': 'bid',
                                'price': yes_ask, 'edge': edge,
                                'contracts': 1.0, 'urgency': 'medium',
                                'reason': f"WEATHER ABOVE: P(above)={prob:.0%}, YES@{yes_ask:.2f}, edge={edge:.0%}",
                                'sport': 'weather',
                            })())
                    elif mtype == 'below':
                        if prob > 0.50 and yes_ask > 0:
                            edge = prob - yes_ask
                            if edge < MIN_EDGE_WEATHER:
                                continue
                            signals.append(type('Sig', (), {
                                'ticker': ticker, 'side': 'bid',
                                'price': yes_ask, 'edge': edge,
                                'contracts': 1.0, 'urgency': 'medium',
                                'reason': f"WEATHER BELOW: P(below)={prob:.0%}, YES@{yes_ask:.2f}, edge={edge:.0%}",
                                'sport': 'weather',
                            })())

                # Rate limit between series
                time.sleep(0.1)

        except Exception as e:
            log.warning(f"[WEATHER] Scan error: {e}")

        if signals:
            log.info(f"[WEATHER] Found {len(signals)} signals from {len(WEATHER_SERIES)} series")
        return signals

    def _to_dollars(self, val) -> float:
        if val is None:
            return 0.0
        try:
            f = float(val)
            return f if f <= 1.0 else f / 100.0
        except (ValueError, TypeError):
            return 0.0

    def _stats(self, balance: float):
        stats = self.positions.get_stats()
        uptime = (time.time() - self.start_time) / 3600
        pnl = balance - self.start_balance
        log.info("━" * 60)
        log.info(f"[STATS] Uptime: {uptime:.1f}h | Scans: {self.scan_count}")
        log.info(f"[STATS] Balance: ${balance:.2f} | Session P&L: ${pnl:+.2f}")
        log.info(f"[STATS] Trades: {stats['trades']} | "
                 f"W/L: {stats['wins']}/{stats['losses']} | "
                 f"Win rate: {stats['win_rate']:.0%}")
        log.info(f"[STATS] Realized: ${stats['realized_pnl']:+.4f} | "
                 f"Open: {stats['positions']}")
        log.info("━" * 60)

    def _final_stats(self):
        balance = self.client.get_balance()
        log.info("=" * 60)
        log.info("[FINAL] Session complete")
        self._stats(balance)


def main():
    banner()
    config = load_config()
    bot = LiveTrader(config)
    bot.run()


if __name__ == '__main__':
    main()
