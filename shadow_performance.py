"""Assess observed short-horizon quotes for unfilled shadow candidates.

This is NOT real trading P&L: even one-contract entry at the displayed ask
may not fill. A candidate lacking a fresh depth-qualified exit is unresolved,
never counted as a win, loss, or zero. No mark-to-expiration shortcut is used.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from account_preflight import strict_decimal


def parse_time(value: str) -> datetime:
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None:
        raise ValueError('Journal timestamp lacks timezone')
    return stamp


def wilson95(wins: int, sample: int) -> list[str] | None:
    """Approximate binomial interval; meaningful only for independent samples."""
    if not sample:
        return None
    if not 0 <= wins <= sample:
        raise ValueError('Invalid positive count')
    n, z = Decimal(sample), Decimal('1.959963984')
    p = Decimal(wins) / n
    z2 = z * z
    center = (p + z2 / (2*n)) / (1 + z2/n)
    margin = z * (p*(1-p)/n + z2/(4*n*n)).sqrt() / (1 + z2/n)
    return [str(max(Decimal(0), center-margin).quantize(Decimal('0.0001'))),
            str(min(Decimal(1), center+margin).quantize(Decimal('0.0001')))]


def evaluate(records: list[dict], *, min_hold_seconds: int = 60,
             max_hold_seconds: int = 300) -> dict:
    if not 0 <= min_hold_seconds < max_hold_seconds <= 1800:
        raise ValueError('Invalid bounded scalp horizon')
    by_ticker: dict[str, list[dict]] = {}
    candidates = []
    for row in records:
        kind = row.get('type')
        if kind == 'quote':
            by_ticker.setdefault(row['ticker'], []).append(row)
        elif kind == 'candidate':
            candidates.append(row)
        elif kind == 'cycle_error':
            raise ValueError('Observation journal contains a data error; do not score an incomplete run')
        elif kind == 'monitor_cycle' and (row.get('source_error') or
                                          not row.get('espn_ok') or not row.get('kalshi_ok')):
            raise ValueError('30-minute observation has a source error; rate is undefined')
        elif kind == 'monitor_end' and row.get('totals', {}).get('source_errors', 0):
            raise ValueError('30-minute observation ended with source errors; rate is undefined')
    for quotes in by_ticker.values():
        quotes.sort(key=lambda q: parse_time(q['observed_at']))
    evaluated = []
    latest_horizon: dict[str, datetime] = {}
    for candidate in sorted(candidates, key=lambda c: parse_time(c['observed_at'])):
        if candidate.get('side') != 'BUY_YES_SHADOW_ONLY':
            raise ValueError('Unsupported shadow outcome; NO cannot be scored as YES')
        start = parse_time(candidate['observed_at'])
        buy = strict_decimal(candidate.get('best_ask'), 'best_ask')
        entry_fee = strict_decimal(candidate.get('estimated_entry_fee_per_contract'), 'entry_fee')
        if not Decimal(0) < buy < Decimal(1) or entry_fee < 0:
            raise ValueError('Invalid entry economics')
        observed = {'ticker': candidate['ticker'], 'entered_shadow_at': start.isoformat(),
                    'status': 'unresolved', 'reason': 'No timely depth-qualified exit quote'}
        horizon = latest_horizon.get(candidate['ticker'])
        if horizon is not None and start <= horizon:
            observed['reason'] = 'Overlapping shadow position; cannot reuse displayed depth'
            evaluated.append(observed)
            continue
        latest_horizon[candidate['ticker']] = start + timedelta(seconds=max_hold_seconds)
        entry_depth = strict_decimal(candidate.get('ask_size'), 'entry ask depth')
        if entry_depth < 1:
            observed['reason'] = 'No displayed depth for one-contract entry'
            evaluated.append(observed)
            continue
        for quote in by_ticker.get(candidate['ticker'], []):
            elapsed = (parse_time(quote['observed_at']) - start).total_seconds()
            if elapsed < min_hold_seconds:
                continue
            if elapsed > max_hold_seconds:
                break
            depth = strict_decimal(quote.get('no_ask_size'), 'NO ask size / YES bid depth')
            bid = strict_decimal(quote.get('yes_bid'), 'exit YES bid')
            if depth < 1 or not Decimal(0) < bid < Decimal(1):
                continue
            # Fee estimate is recomputed at the actual *later* exit quote.
            from main import estimated_taker_fee
            exit_fee = estimated_taker_fee(bid)
            net = bid - buy - entry_fee - exit_fee
            observed = {'ticker': candidate['ticker'], 'entered_shadow_at': start.isoformat(),
                        'observed_exit_at': quote['observed_at'],
                        'status': 'observed_hypothetical', 'entry_ask': str(buy),
                        'exit_bid': str(bid), 'entry_fee_est': str(entry_fee),
                        'exit_fee_est': str(exit_fee), 'net_per_contract_est': str(net),
                        'profitable_if_both_filled': net > 0}
            break
        evaluated.append(observed)
    priced = [row for row in evaluated if row['status'] == 'observed_hypothetical']
    positive = sum(row['profitable_if_both_filled'] for row in priced)
    return {'candidate_count': len(candidates), 'priced_exit_count': len(priced),
            'unresolved_count': len(candidates) - len(priced),
            'positive_hypothetical_outcomes': positive,
            'sum_estimated_net_one_contract_dollars': str(sum(
                (Decimal(row['net_per_contract_est']) for row in priced), Decimal(0))) if priced else None,
            'hypothetical_positive_rate': (str(Decimal(positive) / Decimal(len(priced))) if priced else None),
            'approx_wilson95_if_independent': wilson95(positive, len(priced)),
            'note': 'Hypothetical, not bot fills. Interval assumes independent observed exits and ignores fill uncertainty; neither is assured.',
            'rows': evaluated}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('journal', type=Path)
    p.add_argument('--output', type=Path, default=Path('logs/shadow_performance.json'))
    args = p.parse_args()
    records = [json.loads(line) for line in args.journal.read_text().splitlines() if line.strip()]
    result = evaluate(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('Shadow candidate count:', result['candidate_count'],
          '| priced exits:', result['priced_exit_count'],
          '| unresolved:', result['unresolved_count'])
    print('Realized bot P&L and actual win rate: NOT MEASURED. No orders placed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
