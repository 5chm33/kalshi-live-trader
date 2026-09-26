"""Human-readable noncommercial research scorecard. No network or order code."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def render(d: dict) -> str:
    if d.get('orders') != 0 or d.get('fills') != 0 or d.get('live_strategy_authorized') is not False:
        raise ValueError('Not an offline calibration result')
    observations=d.get('archived_observations');failures=d.get('missing_or_untrusted_dates')
    if not isinstance(observations,list) or not isinstance(failures,list):
        raise ValueError('Missing historical input integrity fields')
    lines=['# NYC temperature: archived-forecast calibration (research only)','',
           f"Archive collected **{d['generated_at_utc']}**; analysis/serial quote reads began **{d.get('reanalyzed_at_utc', d['generated_at_utc'])}**. **No exchange orders, fills, or profit proof.**",
           '', '## Data boundaries', '',
           f"- Prior-day GFS 12:00 UTC archived run; target date **{d['target']}**. Historical dates **{d['train_start']}–{d['holdout_end']}**; train ends **{d['train_end']}**.",
           f'- Matched official NYC station reports: **{len(observations)}**; missing/revised/untrusted dates: **{len(failures)}**.',
           '- Model grid maximum is **not** the NYC settlement-station maximum. Historical latest official station values might have been revised after the first Kalshi-used report; these are calibration labels, not historical verified settlements.',
           '- Open-Meteo archival GFS is available under [non-commercial free API terms](https://open-meteo.com/en/terms); no permission to power an unattended for-profit live feed is inferred.',
           '', '## Holdout and current public books', '']
    ev=d.get('evaluation')
    if not isinstance(ev,dict):
        lines.append('**No validated model output:** some days were absent, revised, or failed source validation. No probability or live trade should be derived from this incomplete set.')
    else:
        lines += [f"Distinct train / subsequent holdout dates: **{ev['training_days']} / {ev['holdout_days']}**.",
                  f"Mean training source-minus-grid error: **{ev['training_mean_error_f']} °F**; holdout absolute error: **{ev['holdout_mae_f']} °F**.",
                  f"Current archived grid forecast maximum: **{d['target_forecast_grid_max_f']} °F**, run initialized {d['target_model_run_utc']}.",
                  f"Comparable archived forecast days within ±5 °F of today's grid maximum: **{ev['within_5f_train_days']} training / {ev['within_5f_holdout_days']} holdout**. Minimum required for a provisional screen: 15 / 10. Forecast regime supported: **{'yes' if ev['supported_forecast_regime'] else 'NO — extrapolation'}**.",
                  '', '| Contract | Estimated YES p | 95% Wilson lower* | Held-out YES days / similar forecast YES days | Conditional holdout Brier model / naive (scored days) | Displayed YES ask + modeled one-contract fee | Provisional screen |',
                  '|---|---:|---:|---:|---:|---:|---|']
        if failures:
            if any(p['provisional_hypothesis_only'] for p in ev['predictions']):
                raise ValueError('Incomplete source set cannot generate a positive screen')
            lines.insert(lines.index('| Contract | Estimated YES p | 95% Wilson lower* | Held-out YES days / similar forecast YES days | Conditional holdout Brier model / naive (scored days) | Displayed YES ask + modeled one-contract fee | Provisional screen |'),
                         '**Incomplete archive: incomplete-source research only.** Missing date(s): '+', '.join(x['date'] for x in failures)+'. No trade screen is permitted.\n')
        for p in ev['predictions']:
            hurdle=p['fee_inclusive_hurdle']
            if p['provisional_hypothesis_only'] and (not ev['supported_forecast_regime'] or any(
                    p.get(k) is None for k in ('model_probability','wilson_lower_95',
                                             'holdout_brier_model','holdout_brier_naive'))):
                raise ValueError('Unsupported probability or Brier cannot generate a positive screen')
            show=lambda n: f'{n:.3f}' if n is not None else 'unsupported'
            lines.append(f"| {p['ticker']} | {show(p['model_probability'])} | {show(p['wilson_lower_95'])} | {p['holdout_true_count']}/{ev['holdout_days']} / {p['similar_holdout_true_count']}/{ev['within_5f_holdout_days']} | {show(p['holdout_brier_model'])} / {show(p['holdout_brier_naive'])} ({p.get('holdout_scored_days',0)}) | {p['yes_ask_dollars'] or 'unavailable'} + {p['one_contract_fee_estimate_dollars'] or 'unavailable'} = {hurdle or 'unavailable'} | {'research hypothesis only' if p['provisional_hypothesis_only'] else 'no'} |")
        lines += ['', '*Wilson interval assumes exchangeable independent **locally comparable** historical residuals. Weather errors are temporally correlated and seasonally varying; the stated 95% coverage is **not** guaranteed and is **not** a trading authorization. Brier comparison uses only subsequent-date holdouts with at least 15 nearby training forecasts and requires at least 20 scored days; unsupported quantities are not estimated. Market prices are not historically backtested.',
                  '', 'At most one point in time is represented by each displayed public quote. Books can change or be empty at submission; modeled taker fee need not equal actual venue fee, particularly under retail cash rounding. **No historical executable Kalshi quotes were collected**, so this is **not a strategy backtest**.']
    lines += ['', '## Sources and next gate', '',
              '- [Archived model-run documentation](https://open-meteo.com/en/docs/single-runs-api); [TWC official climate portal](https://weather.com/kalshi).',
              '- [Kalshi market rules and data](https://docs.kalshi.com/api-reference/market/get-market); [fee schedule](https://kalshi.com/fee-schedule).',
              '- A credible deployment claim additionally needs contract-specific source provenance, *as-of* venue books, a prospective unrevised sample, realized fee-net fills and outcomes, an error bound robust to correlated/seasonal forecast errors, and a positive out-of-sample lower confidence bound. A single scalp lost **$0.0276** in the prior capped pilot.',
              '- **Execution remains disabled**; existing finite weather observation continues separately without account credentials. Do not treat a provisional screen row as an automated buy instruction.', '']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('json_file',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    d=json.loads(a.json_file.read_text());text=render(d)
    if a.output.exists() or a.output.is_symlink():
        raise FileExistsError('Do not replace evidence report')
    if a.output.parent.stat().st_mode & 0o077:
        raise PermissionError('Report output directory must be private')
    a.output.write_text(text,encoding='utf8')
    a.output.chmod(0o600)
    print('report=',a.output,'rows=',len(d.get('archived_observations',[])),'orders=0')


if __name__=='__main__':main()
