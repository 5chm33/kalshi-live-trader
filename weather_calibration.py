"""Historical weather forecast calibration research; no credentials or orders.

One GFS run initialized at 12:00 UTC on the preceding day is queried for
24 local hours of the target day. The exact run, rather than a later
reanalysis or a stitched forecast, is essential to prevent look-ahead.

The public Open-Meteo free API may only be used for non-commercial research
subject to its terms. This script is NOT a live execution signal or service.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import requests

from core.microstructure import effective_fees, fee_estimate
from core.public_market import PublicMarketClient, quote_from_orderbook
from weather_forward import rule_identity, rule_payout, stamp

ARCHIVE = 'https://single-runs-api.open-meteo.com/v1/forecast'
TWC = 'https://weather.com/kalshi/api/climate/primary'
# Obtained from TWC CLI NYC / ICAO KNYC and NWS /stations/KNYC/points,
# documented in the existing weather-forward provenance journal.
LAT, LON = '40.7833', '-73.9667'
MODEL = 'gfs_global'
UA = 'home-weather-calibration-research/1.0 (public, non-commercial, no trading)'


def public_get(url: str, params: dict) -> dict:
    r = requests.get(url, params=params, headers={'User-Agent': UA},
                     timeout=20, allow_redirects=False)
    r.raise_for_status()
    if not 200 <= r.status_code < 300:
        raise ValueError('Public response redirect/invalid status')
    data = r.json()
    if not isinstance(data, dict):
        raise ValueError('Non-object public response')
    return data


def asof_gfs(day: date, get=public_get) -> tuple[float, str]:
    run = (day - timedelta(days=1)).isoformat() + 'T12:00'
    data = get(ARCHIVE, {
        'latitude': LAT, 'longitude': LON, 'hourly': 'temperature_2m',
        'temperature_unit': 'fahrenheit', 'timezone': 'America/New_York',
        'models': MODEL, 'run': run, 'forecast_days': 3,
    })
    if data.get('timezone') != 'America/New_York' or abs(float(data.get('latitude', 0))-float(LAT)) > .1 or abs(float(data.get('longitude', 0))-float(LON)) > .1:
        raise ValueError('Historical model response location/timezone mismatch')
    hourly = data.get('hourly') or {}
    times, temps = hourly.get('time'), hourly.get('temperature_2m')
    if not isinstance(times, list) or not isinstance(temps, list) or len(times) != len(temps):
        raise ValueError('Incomplete archived hourly forecast')
    vals = [(t, v) for t, v in zip(times, temps) if isinstance(t, str) and t.startswith(day.isoformat() + 'T')]
    if len(vals) not in (23, 24, 25) or len({t for t, _ in vals}) != len(vals):
        raise ValueError('Missing/duplicate target local hours')
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for _, v in vals):
        raise ValueError('Non-finite/missing temperature')
    return max(float(v) for _, v in vals), run


def official_nyc(day: date, get=public_get) -> int:
    data = get(TWC, {'date': day.isoformat()})
    if data.get('date') != day.isoformat() or not isinstance(data.get('results'), list):
        raise ValueError('TWC report date/schema mismatch')
    rows = [x for x in data['results'] if isinstance(x, dict) and isinstance(x.get('station'), dict)
            and x['station'].get('cliId') == 'NYC']
    if len(rows) != 1:
        raise ValueError('Ambiguous NYC station report')
    row = rows[0]
    station = row['station']
    info = row.get('data')
    if (station.get('city') != 'New York City' or station.get('icao') != 'KNYC'
            or station.get('timezone') != 'America/New_York' or row.get('status') != 'official'
            or not isinstance(info, dict) or info.get('isOfficial') is not True
            or info.get('reportDate') != day.isoformat()
            or isinstance(info.get('maxTemp'), bool) or not isinstance(info.get('maxTemp'), int)
            or not -50 <= info['maxTemp'] <= 140):
        raise ValueError('Missing/untrusted or revised official NYC CLI maximum')
    return info['maxTemp']


def one_day(day: date) -> dict:
    forecast, run = asof_gfs(day)
    actual = official_nyc(day)
    return {'date': day.isoformat(), 'model_run_utc': run + 'Z',
            'grid_forecast_max_f': forecast, 'official_station_max_f': actual,
            'error_station_minus_grid_f': round(actual - forecast, 3),
            'forecast_origin': ARCHIVE, 'settlement_report_origin': TWC}


def wilson_lower(successes: int, n: int, z: float = 1.96) -> float:
    if n <= 0 or not 0 <= successes <= n:
        raise ValueError('Bad binomial counts')
    p = successes / n
    denom = 1 + z * z / n
    return max(0., (p + z*z/(2*n) - z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / denom)


def event_probability(forecast: float, errors: list[float], rule: str) -> tuple[float, float]:
    if not errors or any(not math.isfinite(e) for e in errors):
        raise ValueError('Insufficient residual data')
    successes = sum(rule_payout(rule, int(round(forecast + e))) for e in errors)
    return (successes + 1) / (len(errors) + 2), wilson_lower(successes, len(errors))


def calibration(rows: list[dict], train_end: date, markets: list[dict], target_forecast: float, fees: tuple,
                public: PublicMarketClient) -> dict:
    train = [r for r in rows if date.fromisoformat(r['date']) <= train_end]
    holdout = [r for r in rows if date.fromisoformat(r['date']) > train_end]
    if len(train) < 60 or len(holdout) < 20:
        raise ValueError('Insufficient chronological train/holdout days')
    residuals = [r['error_station_minus_grid_f'] for r in train]
    nearby_train=sum(abs(r['grid_forecast_max_f']-target_forecast) <= 5 for r in train)
    nearby_holdout=sum(abs(r['grid_forecast_max_f']-target_forecast) <= 5 for r in holdout)
    # Only residuals from a comparable archived forecast regime may influence
    # the probability. A mere support count alongside all-season errors is unsafe.
    target_errors=[r['error_station_minus_grid_f'] for r in train
                   if abs(r['grid_forecast_max_f']-target_forecast) <= 5]
    supported=nearby_train >= 15 and nearby_holdout >= 10
    predictions = []
    for m in markets:
        rule = m['rules_primary']
        # Verify the whole contract-rule grammar even if one side has no ask.
        rule_payout(rule, 70)
        model_prob, lower = event_probability(target_forecast, target_errors, rule) if supported else (None, None)
        base = (1 + sum(rule_payout(rule, r['official_station_max_f']) for r in train))/(len(train)+2)
        near_holdout=[r for r in holdout if abs(r['grid_forecast_max_f']-target_forecast) <= 5]
        held_true=sum(rule_payout(rule,r['official_station_max_f']) for r in holdout)
        nearby_true=sum(rule_payout(rule,r['official_station_max_f']) for r in near_holdout)
        valid_holdout=[]
        for r in holdout:
            local=[x['error_station_minus_grid_f'] for x in train
                   if abs(x['grid_forecast_max_f']-r['grid_forecast_max_f']) <= 5]
            if len(local) >= 15:
                valid_holdout.append((r,event_probability(r['grid_forecast_max_f'],local,rule)[0]))
        # A handful of scored dates cannot validate a probability model.
        model_brier=(sum((p-int(rule_payout(rule,r['official_station_max_f'])))**2
                         for r,p in valid_holdout)/len(valid_holdout)) if supported and len(valid_holdout) >= 20 else None
        baseline_brier=(sum((base-int(rule_payout(rule,r['official_station_max_f'])))**2
                            for r,p in valid_holdout)/len(valid_holdout)) if model_brier is not None else None
        quote = quote_from_orderbook(public.get_orderbook(m['ticker'], depth=1))
        ask = quote.yes_ask if quote and quote.yes_ask_size >= 1 else None
        fee = fee_estimate(ask, *fees, maker=False) if ask is not None else None
        hurdle = ask + fee if ask is not None else None
        predictions.append({'ticker':m['ticker'],'model_probability':round(model_prob,4) if model_prob is not None else None,
                            'wilson_lower_95':round(lower,4) if lower is not None else None,
                            'holdout_true_count':held_true,
                            'similar_holdout_true_count':nearby_true,
                            'holdout_scored_days':len(valid_holdout),
                            'holdout_brier_model':round(model_brier,4) if model_brier is not None else None,
                            'holdout_brier_naive':round(baseline_brier,4) if baseline_brier is not None else None,
                            'yes_ask_dollars':str(ask) if ask is not None else None,
                            'one_contract_fee_estimate_dollars':str(fee) if fee is not None else None,
                            'fee_inclusive_hurdle':str(hurdle) if hurdle is not None else None,
                            'one_unit_displayed_depth':str(quote.yes_ask_size) if ask is not None else None,
                            'provisional_hypothesis_only':bool(supported and hurdle is not None and
                                model_brier is not None and lower > float(hurdle)+0.05 and
                                model_brier < baseline_brier)})
    return {'training_days':len(train),'holdout_days':len(holdout),
            'training_mean_error_f':round(sum(residuals)/len(residuals),3),
            'holdout_mae_f':round(sum(abs(r['error_station_minus_grid_f']) for r in holdout)/len(holdout),3),
            'within_5f_train_days':nearby_train,'within_5f_holdout_days':nearby_holdout,
            'supported_forecast_regime':supported,
            'predictions':predictions}


def evaluate_archive(result: dict) -> dict:
    """Exploratory only if any archived source day failed validation."""
    rows = result['archived_observations']
    failures = result['missing_or_untrusted_dates']
    start, end, train_end, target = (date.fromisoformat(result[k]) for k in
                                     ('train_start', 'holdout_end', 'train_end', 'target'))
    required = {(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)}
    available = [r['date'] for r in rows]
    skipped = [r['date'] for r in failures]
    if (result.get('orders') != 0 or result.get('fills') != 0 or
            result.get('live_strategy_authorized') is not False or
            len(available) != len(set(available)) or len(skipped) != len(set(skipped)) or
            set(available) & set(skipped) or set(available) | set(skipped) != required or
            len(failures) > 5):
        raise ValueError('Archived sample integrity or coverage failure')
    for r in rows:
        day=date.fromisoformat(r['date'])
        if (r.get('model_run_utc') != (day-timedelta(days=1)).isoformat()+'T12:00Z'
                or r.get('forecast_origin') != ARCHIVE or r.get('settlement_report_origin') != TWC
                or not isinstance(r.get('official_station_max_f'),int)):
            raise ValueError('Historical source provenance mismatch')
    public=PublicMarketClient();event=public.get_event('KXHIGHNY-'+target.strftime('%y%b%d').upper())
    markets=event['markets'];city,cli=rule_identity(markets,target)
    if (city,cli) != ('New York City','CLINYC'):
        raise ValueError('Binding market rule does not identify the archived NYC CLI station')
    target_forecast, target_run=asof_gfs(target)
    from weather_forward import require_source
    series=public.get_series('KXHIGHNY');require_source(series.get('settlement_sources'))
    fees=effective_fees(series,event)
    result['target_forecast_grid_max_f']=target_forecast
    result['target_model_run_utc']=target_run+'Z'
    value=calibration(rows,train_end,markets,target_forecast,fees,public)
    value['incomplete_source_days']=len(failures)
    if failures:
        for p in value['predictions']:
            p['provisional_hypothesis_only']=False
    result['evaluation']=value
    return result


def save_result(output: Path, result: dict) -> None:
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.parent.stat().st_mode & 0o077:
        raise PermissionError('Research output directory must be private')
    fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(result,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())


def run(output: Path, *, start: date, train_end: date, end: date, target: date, workers: int = 3) -> dict:
    if not (start < train_end < end < target) or workers not in range(1,5) or (end-start).days > 180:
        raise ValueError('Bad fixed calibration window')
    if output.exists() or output.is_symlink():
        raise FileExistsError('Refuse to replace research evidence')
    event=PublicMarketClient().get_event('KXHIGHNY-'+target.strftime('%y%b%d').upper())
    if rule_identity(event['markets'],target) != ('New York City','CLINYC'):
        raise ValueError('Binding market rule changed station; refusing historical NYC labels')
    days = [start + timedelta(days=i) for i in range((end-start).days+1)]
    rows, failures = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = {pool.submit(one_day, day):day for day in days}
        for i, future in enumerate(as_completed(jobs), 1):
            try: rows.append(future.result())
            except Exception as ex: failures.append({'date':jobs[future].isoformat(),'reason':type(ex).__name__})
            if i % 25 == 0 or i == len(jobs):
                print(f'archive_progress completed={i}/{len(jobs)} valid={len(rows)} failures={len(failures)}',flush=True)
    rows.sort(key=lambda r:r['date']);failures.sort(key=lambda r:r['date'])
    # Missing dates remain explicit. The exploratory model can use validated
    # dates, but an incomplete archive never generates a positive screen.
    result = {'generated_at_utc':stamp(datetime.now(timezone.utc)),
              'sources':[ARCHIVE,TWC,'https://open-meteo.com/en/docs/single-runs-api',
                         'https://open-meteo.com/en/terms'],
              'train_start':start.isoformat(),'train_end':train_end.isoformat(),
              'holdout_end':end.isoformat(),'target':target.isoformat(),
              'archived_observations':rows,'missing_or_untrusted_dates':failures,
              'orders':0,'fills':0,'live_strategy_authorized':False}
    if len(failures) <= 5:
        result=evaluate_archive(result)
    save_result(output,result)
    return result


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--start',type=date.fromisoformat,default=date(2026,6,1))
    parser.add_argument('--train-end',type=date.fromisoformat,default=date(2026,8,31))
    parser.add_argument('--end',type=date.fromisoformat,default=date(2026,9,25))
    parser.add_argument('--target',type=date.fromisoformat,default=date(2026,9,27))
    parser.add_argument('--reanalyze',type=Path,help='Reuse an immutable previous archive; no bulk API refetch')
    args=parser.parse_args()
    if args.reanalyze:
        if args.output.exists() or args.output.is_symlink():
            raise FileExistsError('Refuse to replace research evidence')
        original=json.loads(args.reanalyze.read_text())
        original.pop('evaluation',None)
        original['reanalyzed_at_utc']=stamp(datetime.now(timezone.utc))
        original['source_archive']=str(args.reanalyze)
        result=evaluate_archive(original)
        save_result(args.output,result)
    else:
        result=run(args.output,start=args.start,train_end=args.train_end,end=args.end,target=args.target)
    print('archive_done rows=',len(result['archived_observations']),'failed_dates=',len(result['missing_or_untrusted_dates']),
          'has_validation=',bool(result.get('evaluation')),'orders=0',flush=True)


if __name__=='__main__':main()
