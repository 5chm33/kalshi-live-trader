"""Report source alignment from a public-only weather journal; no trading inference."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from weather_forward import load_journal


def render(journal: Path) -> str:
    rows, decisions, labels, ended = load_journal(journal)
    if not rows or any(row.get('paper_orders') != 0 or row.get('real_orders') != 0
                       or row.get('real_fills') != 0 for row in rows):
        raise ValueError('Journal claims trading activity; not a public-only study')
    final_rows = {row['target_date']: row for row in rows
                  if row.get('type') == 'source_and_venue_label' and row['target_date'] in labels}
    revisions = {row['target_date'] for row in rows
                 if row.get('type') == 'source_revision_or_disagreement'}
    observed = [row for row in decisions.values() if row['type'] == 'decision_observation']
    lines = ['# Daily-temperature forward study — public data only', '',
             '**Not a trading-performance report.** No live or paper order was sent; quote snapshots do not establish fills, and the NWS grid maximum is an uncalibrated predictor, not a settlement probability.', '',
             f'- Registration: {rows[0]["observed_at_utc"]}; frozen last target: {rows[0]["last_target"]}; journal ended: {ended}.',
             f'- Distinct scheduled dates recorded: {len(decisions)}; valid pre-event observations: {len(observed)}; errors/missed cutoffs: {len(decisions)-len(observed)}.',
             f'- Source/venue double-confirmed final labels: {len(labels)}; observed dates still awaiting both: {len(observed)-len(labels)}.',
             '- Actual venue orders/fills: **0/0**. Fee-adjusted returns and win percentage: **undefined**.', '',
             '## Captured dates', '',
             '| Climate date | 18:00 local decision | NWS grid proxy max (°F) | Final TWC CLI max (°F) | Kalshi settled? | Notes |',
             '| --- | --- | ---: | ---: | --- | --- |']
    for key, row in sorted(decisions.items()):
        if row['type'] != 'decision_observation':
            reason = row.get('reason',row['type']).replace('|','/').replace('\n',' ')
            lines.append(f'| {key} | {row["type"]} | — | — | No | {reason} |')
            continue
        forecast=row['forecast']['uncalibrated_grid_max_f']
        final=final_rows.get(key)
        source_value='—'
        settled='No'
        if final is not None:
            source_value=str(final['twc_station_row']['data']['maxTemp'])
            settled='Yes'
        usable=sum(1 for b in row['books'] if b.get('quote') is not None and
                   Decimal(b['quote']['yes_ask_size_fp']) >= 1)
        note=f'{usable}/{len(row["books"])} one-contract YES asks displayed; not fills'
        if key in revisions:
            note += '; source revision or disagreement UNRESOLVED'
        lines.append(f'| {key} | captured | {forecast} | {source_value} | {settled} | {note} |')
    if not decisions:
        lines.append('| — | Waiting for first registered cutoff | — | — | No | — |')
    lines += ['', '## Displayed one-contract break-even probability hurdles', '',
              '**Not a forecast probability or trade signal.** Values are cutoff-time public asks plus the archived conservative one-unit taker-fee ceiling. A later fill may differ; model uncertainty requires a further predeclared margin.', '',
              '| Climate date | Contract | YES ask + fee hurdle | NO ask + fee hurdle | Displayed one-unit depth |',
              '| --- | --- | ---: | ---: | --- |']
    have_complete_book=False
    for day, row in sorted(decisions.items()):
        if row['type'] != 'decision_observation' or 'markets' not in row:
            continue
        markets={m['ticker']:m for m in row['markets']}
        if len(markets) != len(row['books']) or {b['ticker'] for b in row['books']} != set(markets):
            raise ValueError('Weather report market/book identity mismatch')
        for book in row['books']:
            have_complete_book=True
            q=book.get('quote')
            if q is None:
                lines.append(f'| {day} | {book["ticker"]} | — | — | one-sided/empty; ineligible |')
                continue
            yes=Decimal(q['yes_ask'])+Decimal(q['indicative_yes_taker_fee_ceiling'])
            no=Decimal(q['no_ask'])+Decimal(q['indicative_no_taker_fee_ceiling'])
            ydepth=Decimal(q['yes_ask_size_fp'])
            ndepth=Decimal(q['no_ask_size_fp'])
            if not (0<yes<=1 and 0<no<=1 and ydepth>=0 and ndepth>=0):
                raise ValueError('Malformed weather fee hurdle or displayed book depth')
            lines.append(f'| {day} | {book["ticker"]} | '
                         f'{yes:.4f} ({ydepth:.2f} shown) | {no:.4f} ({ndepth:.2f} shown) | '
                         f'{"both ≥1" if min(ydepth,ndepth)>=1 else "insufficient for one side"} |')
    if not have_complete_book:
        lines.append('| — | No full market/book rows yet | — | — | — |')
    lines += ['', '**Interpretation:** At least 30 complete source-matched days are needed before freezing any probability calibration rule, followed by at least 30 new out-of-sample dates; neither threshold proves future profitability. TWC revisions, market-rule changes, or missing books remain visible, not backfilled.', '',
              'Sources: [Kalshi daily-weather rules](https://help.kalshi.com/en/articles/13823837-weather-markets), [TWC/Kalshi final climate portal](https://weather.com/kalshi), [NWS forecast API](https://www.weather.gov/documentation/services-web-API).', '']
    return '\n'.join(lines)


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('journal', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args()
    text=render(a.journal)
    if a.output.is_symlink():
        raise PermissionError('Report symlink forbidden')
    a.output.write_text(text)
    a.output.chmod(0o600)
    print('weather_report_written',a.output,'real_orders=0')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
