"""Summarize a bounded public-data observation without inventing trades or wins."""
from __future__ import annotations

import argparse
import json
from collections import Counter
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
    status = Counter('Kalshi' if r.get('espn_ok') and not r.get('kalshi_ok') else
                     'ESPN' if not r.get('espn_ok') else 'none' for r in cycles)
    all_source_valid = totals.get('source_errors') == 0 and status['none'] == len(cycles)
    candidates = totals.get('candidates', 0)
    if not isinstance(candidates, int) or candidates < 0:
        raise ValueError('Invalid candidate total')
    errors = [r.get('source_error', '') for r in cycles if r.get('source_error')]
    tls_errors = sum('certificate' in msg.lower() or 'sslerror' in msg.lower() for msg in errors)
    lines = [
        '# Thirty-minute Kalshi public-data observation',
        '',
        f"**Window (UTC):** {start['at']} – {end['ended_at']} "
        f"({end['elapsed_seconds']} seconds; requested {start['duration_seconds']} seconds).",
        '',
        '| Measure | Observed |', '| --- | ---: |',
        f"| Completed scan attempts | {len(cycles)} |",
        f"| ESPN reads succeeded | {totals.get('espn_ok')} |",
        f"| Kalshi market cycles completed | {totals.get('kalshi_ok')} |",
        f"| Source failures | {totals.get('source_errors')} |",
        f"| TLS/certificate failures | {tls_errors} |",
        f"| Strict same-game/time matches | {totals.get('strict_matches')} |",
        f"| Uncalibrated candidates | {candidates} |",
        '| Actual bot orders | 0 |',
        '',
        '**Conclusion:** ' + ('Both public feeds remained readable during the observation.'
                              if all_source_valid else
                              'At least one source failed; the session cannot validate a trading signal or exchange execution.'),
        'No real order was sent by this read-only code. **Actual bot win rate and realized bot P&L are undefined**, not 0% or 100%.',
    ]
    if not candidates:
        lines.append('No candidate was observed; hypothetical win rate is also undefined.')
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
