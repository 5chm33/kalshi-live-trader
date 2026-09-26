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
