"""30-minute public-data observation. NO account writes, no order path.

A failed/certificate-invalid API read remains an explicit error. Never replace
an inaccessible orderbook with synthetic prices or count an unknown as a win.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from core.espn_feed import ESPNFeed
from core.market_matcher import MarketMatcher
from core.public_market import PublicMarketClient
from main import observe_cycle
from strategies.latency_sniper import LatencySniper


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(duration_seconds: int, interval_seconds: float, output_path: Path) -> dict:
    if not 60 <= duration_seconds <= 7200 or not 5 <= interval_seconds <= 300:
        raise ValueError('Invalid bounded observation duration or interval')
    if output_path.is_symlink() or (output_path.exists() and
            stat.S_IMODE(output_path.stat().st_mode) & 0o077):
        raise PermissionError('Existing observation journal must be a private regular file')
    output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
    fd = os.open(output_path, flags, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise PermissionError('Observation journal must be a regular file')
    start_wall = now()
    started = time.monotonic()
    deadline = started + duration_seconds
    feed = ESPNFeed(sports=['mlb'])
    market = PublicMarketClient()
    matcher = MarketMatcher(market)
    strategy = LatencySniper()
    totals = dict(cycles=0, espn_ok=0, kalshi_ok=0, source_errors=0,
                  quote_errors=0,
                  games_in_progress=0, strict_matches=0, candidates=0,
                  real_orders=0)
    with os.fdopen(fd, 'a', encoding='utf-8') as output:
        output.write(json.dumps({'type': 'monitor_start', 'at': start_wall,
                                 'duration_seconds': duration_seconds,
                                 'interval_seconds': interval_seconds,
                                 'execution': 'read_only'}) + '\n')
        output.flush()
        while time.monotonic() < deadline:
            totals['cycles'] += 1
            row = {'type': 'monitor_cycle', 'observed_at': now(),
                   'cycle': totals['cycles'], 'espn_ok': False,
                   'kalshi_ok': False, 'quote_errors': 0, 'real_orders': 0}
            try:
                observed = feed.poll()
                row['espn_ok'] = True
                totals['espn_ok'] += 1
                row['games_in_progress'] = len(observed[0])
                row['score_changes'] = len(observed[1])
                totals['games_in_progress'] += len(observed[0])
                try:
                    counters = observe_cycle(feed, matcher, market, strategy, output,
                                             observed=observed)
                    row['kalshi_ok'] = True
                    totals['kalshi_ok'] += 1
                    totals['strict_matches'] += counters['strict_matches']
                    totals['candidates'] += counters['heuristic_candidates']
                    totals['quote_errors'] += counters['quote_errors']
                    row['strict_matches'] = counters['strict_matches']
                    row['candidates'] = counters['heuristic_candidates']
                    row['quote_errors'] = counters['quote_errors']
                except Exception as exc:
                    row['source_error'] = f'Kalshi/market: {type(exc).__name__}: {str(exc)[:200]}'
            except Exception as exc:
                row['source_error'] = f'ESPN: {type(exc).__name__}: {str(exc)[:200]}'
            if 'source_error' in row:
                totals['source_errors'] += 1
            output.write(json.dumps(row) + '\n')
            output.flush()
            if totals['cycles'] == 1 or totals['cycles'] % 6 == 0:
                print(f"elapsed={int(time.monotonic()-started)}s "
                      f"cycles={totals['cycles']} ESPN={totals['espn_ok']} "
                      f"Kalshi={totals['kalshi_ok']} candidates={totals['candidates']} "
                      f"errors={totals['source_errors']}", flush=True)
            next_due = started + totals['cycles'] * interval_seconds
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(remaining, max(0, next_due - time.monotonic())))
        result = {'type': 'monitor_end', 'started_at': start_wall, 'ended_at': now(),
                  'elapsed_seconds': round(time.monotonic()-started, 2),
                  'totals': totals, 'win_rate': None, 'realized_pnl': None,
                  'note': 'A read-only observer cannot guarantee trades or measure realized bot profitability.'}
        output.write(json.dumps(result) + '\n')
        output.flush()
        os.fsync(output.fileno())
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--duration-seconds', type=int, default=1800)
    p.add_argument('--interval-seconds', type=float, default=10)
    p.add_argument('--output', type=Path, default=Path('logs/monitor_30m.jsonl'))
    args = p.parse_args()
    try:
        result = run(args.duration_seconds, args.interval_seconds, args.output)
    except Exception as exc:
        print(f'OBSERVATION STOPPED: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
