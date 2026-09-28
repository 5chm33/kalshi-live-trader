"""Summarize a bounded public-data observation without inventing trades or wins."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


def summarize(records: list[dict]) -> str:
    starts = [r for r in records if r.get('type') == 'monitor_start']
    ends = [r for r in records if r.get('type') == 'monitor_end']
    cycles = [r for r in records if r.get('type') == 'monitor_cycle']
    if len(starts) != 1 or len(ends) != 1 or not cycles:
        raise ValueError('Incomplete monitor journal; a full-window report is not possible')
    start, end = starts[0], ends[0]
    totals = end.get('totals')
    if (not isinstance(totals, dict) or totals.get('cycles') != len(cycles)
            or end.get('elapsed_seconds', 0) < start.get('duration_seconds', 0) - 1):
        raise ValueError('Monitor duration or cycle totals do not reconcile')
    if any(r.get('real_orders') != 0 for r in cycles) or totals.get('real_orders') != 0:
        raise ValueError('This read-only monitor cannot attribute exchange orders')
    wall_seconds = (datetime.fromisoformat(end['ended_at']) -
                    datetime.fromisoformat(start['at'])).total_seconds()
    samples = [datetime.fromisoformat(r['observed_at']) for r in cycles]
    largest_gap = max(((b-a).total_seconds() for a, b in zip(samples, samples[1:])),
                      default=0)
    interrupted = (wall_seconds > 1.2 * start['duration_seconds'] or
                   largest_gap > max(30, 3 * start['interval_seconds']))
    status = Counter('Kalshi' if r.get('espn_ok') and not r.get('kalshi_ok') else
                     'ESPN' if not r.get('espn_ok') else 'none' for r in cycles)
    quote_errors = totals.get('quote_errors')
    if quote_errors is not None and (not isinstance(quote_errors, int) or quote_errors < 0 or
            quote_errors != sum(r.get('quote_errors', 0) for r in cycles)):
        raise ValueError('Quoted book error totals do not reconcile')
    unusable_books = totals.get('unusable_books')
    if unusable_books is not None and (not isinstance(unusable_books, int) or
            unusable_books < 0 or unusable_books != sum(r.get('unusable_books', 0) for r in cycles)):
        raise ValueError('Unusable orderbook totals do not reconcile')
    two_sided_pairs = totals.get('two_sided_game_pairs')
    if two_sided_pairs is not None and (not isinstance(two_sided_pairs, int) or
            two_sided_pairs < 0 or two_sided_pairs > totals.get('strict_matches', -1) or
            two_sided_pairs != sum(r.get('two_sided_game_pairs', 0) for r in cycles)):
        raise ValueError('Two-sided game pair totals do not reconcile')
    all_source_valid = (not interrupted and totals.get('source_errors') == 0 and
                        quote_errors == 0 and status['none'] == len(cycles))
    candidates = totals.get('candidates', 0)
    if not isinstance(candidates, int) or candidates < 0:
        raise ValueError('Invalid candidate total')
    errors = [r.get('source_error', '') for r in cycles if r.get('source_error')]
    tls_errors = sum('certificate' in msg.lower() or 'sslerror' in msg.lower() for msg in errors)
    lines = [
        '# Thirty-minute Kalshi public-data observation',
        '',
        f"**Window (UTC):** {start['at']} – {end['ended_at']}.",
        f"**Active runtime:** {end['elapsed_seconds']} seconds; **wall-clock span:** "
        f"{wall_seconds:.1f} seconds; requested {start['duration_seconds']} seconds.",
        '',
        '| Measure | Observed |', '| --- | ---: |',
        f"| Completed scan attempts | {len(cycles)} |",
        f"| ESPN reads succeeded | {totals.get('espn_ok')} |",
        f"| Kalshi market cycles completed | {totals.get('kalshi_ok')} |",
        f"| Source failures | {totals.get('source_errors')} |",
        f"| Incomplete/failed orderbooks | {quote_errors if quote_errors is not None else 'unknown (legacy journal)'} |",
        f"| One-sided/empty book snapshots (not executable) | {unusable_books if unusable_books is not None else 'unknown (legacy journal)'} |",
        f"| TLS/certificate failures | {tls_errors} |",
        f"| Largest gap between scans (seconds) | {largest_gap:.1f} |",
        f"| Sampling continuity | {'interrupted' if interrupted else 'not interrupted'} |",
        f"| Strict same-game/time matches | {totals.get('strict_matches')} |",
        f"| Matched game snapshots with two executable team books | {two_sided_pairs if two_sided_pairs is not None else 'unknown (legacy journal)'} |",
        f"| Uncalibrated candidates | {candidates} |",
        '| Actual bot orders | 0 |',
        '',
        '**Conclusion:** ' + ('Both public feeds remained readable during the observation.'
                              if all_source_valid else
                              'The sampling window was interrupted, a source failed, or executable quotes were missing; this cannot validate a trading signal or exchange execution.'),
        'No real order was sent by this read-only code. **Actual bot win rate and realized bot P&L are undefined**, not 0% or 100%.',
    ]
    if not candidates:
        lines.append('No candidate was observed; hypothetical win rate is also undefined.')
    if unusable_books:
        lines.append(f'{unusable_books} matched book snapshots had no two-sided executable quote. '
                     'These are illiquid markets, not fabricated bids or observed opportunities.')
    lines.append('Repeated game/book snapshots are not independent trading opportunities.')
    lines.extend(['', 'API access and a high usage tier cannot establish strategy profitability. '
                  'Real-money activation still requires a validated fee-adjusted edge, '
                  'exclusive inventory, independently verified fills/exits, and a durable kill switch.', ''])
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('journal', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = summarize([json.loads(line) for line in args.journal.read_text().splitlines() if line.strip()])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report)
    print(args.output.resolve())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
