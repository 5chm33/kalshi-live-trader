"""Summarize private forward-research journals; never infer fills or enable trading."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import stat

from summarize_monitor import summarize
from shadow_performance import evaluate


def report(directory: Path) -> str:
    files = sorted(directory.glob('*.jsonl'))
    if not files:
        raise ValueError('No real forward journal segments found')
    totals = Counter()
    completed = 0
    partial = 0
    bad = []
    shadow_priced = 0
    shadow_net = 0.0
    for path in files:
        if path.is_symlink() or not path.is_file():
            raise PermissionError('Forward journal must be a regular file')
        try:
            records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        except json.JSONDecodeError:
            partial += 1
            continue
        if any(r.get('real_orders', 0) != 0 for r in records if r.get('type') == 'monitor_cycle') or any(
                r.get('totals', {}).get('real_orders', 0) != 0 for r in records
                if r.get('type') == 'monitor_end'):
            raise ValueError('Read-only journal unexpectedly claims actual bot orders')
        if not any(r.get('type') == 'monitor_end' for r in records):
            partial += 1
            continue
        try:
            summary = summarize(records)
        except (ValueError, KeyError, TypeError) as exc:
            bad.append(f'{path.name}: {type(exc).__name__}')
            continue
        end = next(r for r in records if r.get('type') == 'monitor_end')
        count = end['totals']
        completed += 1
        for k in ('cycles', 'espn_ok', 'kalshi_ok', 'source_errors', 'quote_errors',
                  'unusable_books', 'strict_matches', 'two_sided_game_pairs',
                  'candidates', 'real_orders'):
            if k in count:
                totals[k] += count[k]
        if 'Sampling continuity | interrupted' in summary or count.get('source_errors', 0) or count.get('quote_errors', 0):
            bad.append(f'{path.name}: incomplete data or sampling gap')
            continue
        try:
            shadow = evaluate(records)
        except (KeyError, ValueError, TypeError):
            bad.append(f'{path.name}: shadow evaluation incomplete')
            continue
        shadow_priced += shadow['priced_exit_count']
        shadow_net += sum(float(r['net_per_contract_est']) for r in shadow['rows']
                          if r['status'] == 'observed_hypothetical')
    if totals['real_orders'] != 0:
        raise ValueError('Read-only journal unexpectedly claims actual bot orders')
    lines = [
        '# Forward Kalshi research: current real-data status', '',
        f'- Completed, validated segments: **{completed}**; unfinished segments: **{partial}**.',
        f'- Completed public ESPN/Kalshi cycles: **{totals["espn_ok"]}/{totals["kalshi_ok"]}** of **{totals["cycles"]}**.',
        f'- Source errors: **{totals["source_errors"]}**; failed/malformed book reads: **{totals["quote_errors"]}**.',
        f'- Valid one-sided or empty book snapshots (not executable): **{totals["unusable_books"]}**.',
        f'- Repeated strict game matches: **{totals["strict_matches"]}**; matched-game snapshots with two executable team books: **{totals["two_sided_game_pairs"]}**. These are *not independent opportunities*.',
        f'- Uncalibrated candidates: **{totals["candidates"]}**; depth-qualified hypothetical short-horizon exits: **{shadow_priced}**.',
        f'- Observed hypothetical one-contract net across evaluable excerpts: **{f"${shadow_net:.4f}" if shadow_priced else "unavailable (no observed exits)"}**. This is not realized P&L or an achievable fill.',
        f'- Actual bot orders: **{totals["real_orders"]}**; realized bot P&L and bot win rate: **undefined**.',
        '',
        f'**Decision: LIVE TRADING DISABLED.** {len(bad)} segments could not be completely scored.',
        'Positive shadow prices would still not prove fill quality, fee-adjusted edge, inventory ownership, or executable exits. This report cannot switch on live orders.',
        '',
    ]
    return '\n'.join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory', type=Path)
    p.add_argument('--output', required=True, type=Path)
    args = p.parse_args()
    text = report(args.directory)
    path = args.output
    if path.is_symlink() or (path.exists() and (not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077)):
        raise PermissionError('Report path must be a private regular file')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(text)
    print(path.resolve())


if __name__ == '__main__':
    main()
