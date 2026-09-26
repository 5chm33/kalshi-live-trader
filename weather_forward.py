"""Finite public-data weather provenance study. No keys, order endpoints or simulated fills.

This captures ONE next-day New York daily-temperature event at a frozen local
cutoff. TWC's published final climate report and Kalshi's settlement are
recorded separately; a NWS grid forecast is an UNCALIBRATED predictor, never
substituted for the authoritative observation.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from core.microstructure import effective_fees, fee_estimate
from core.public_market import MarketDataError, PublicMarketClient, quote_from_orderbook

SERIES = 'KXHIGHNY'
LOCAL_TZ = ZoneInfo('America/New_York')
FIRST_TARGET = date(2026, 9, 27)
LAST_TARGET = date(2026, 10, 3)
DEADLINE = datetime(2026, 10, 5, 22, 5, tzinfo=timezone.utc)
RULE = re.compile(r'\bmaximum temperature recorded at ([^()]+?) \((CLI[A-Z]{3})\) for '
                  r'([A-Z][a-z]{2} \d{1,2}, 20\d{2}), is\b')
THRESHOLD = re.compile(r'\bis (?:between (?P<low>-?\d+)-(?P<high>-?\d+)|'
                       r'less than (?P<less>-?\d+)|greater than (?P<greater>-?\d+))°?'
                       r'\s+fahrenheit according to The Weather Company\b', re.IGNORECASE)
SOURCE_URL = 'https://weather.com/kalshi/api/climate/primary'
NWS_ROOT = 'https://api.weather.gov'
NWS_HEADERS = {'User-Agent': 'kalshi-home-weather-research/1.0 (public, read-only)',
               'Accept': 'application/geo+json'}
TWC_HEADERS = {'User-Agent': 'kalshi-home-weather-research/1.0 (public, read-only)'}


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def parse_stamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp lacks timezone')
    return result.astimezone(timezone.utc)


def cutoff(target: date) -> datetime:
    prior = target - timedelta(days=1)
    return datetime(prior.year, prior.month, prior.day, 18, tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def require_source(sources: object) -> None:
    if not isinstance(sources, list) or not any(
        isinstance(s, dict) and s.get('name') == 'The Weather Company' and
        s.get('url') == 'https://weather.com/kalshi' for s in sources
    ):
        raise MarketDataError('Unverified contract-specific TWC settlement source')


def rule_identity(markets: list[dict], target: date) -> tuple[str, str]:
    if not markets or len({m.get('ticker') for m in markets}) != len(markets):
        raise MarketDataError('No unique weather markets')
    identities = set()
    for m in markets:
        text = m.get('rules_primary')
        matches = RULE.findall(text) if isinstance(text, str) else []
        if len(matches) != 1:
            raise MarketDataError('Missing or ambiguous source station/date in market rule')
        city, cli, day_text = matches[0]
        day = datetime.strptime(day_text, '%b %d, %Y').date()
        identities.add((city.strip(), cli, day))
        if m.get('status') != 'active' or m.get('is_provisional') is True:
            raise MarketDataError('Inactive/provisional weather market')
    if len(identities) != 1:
        raise MarketDataError('Weather markets have inconsistent source station/date')
    city, cli, day = identities.pop()
    if day != target:
        raise MarketDataError('Wrong target date in binding weather rule')
    return city, cli


def rule_payout(rule: str, max_temp: int) -> bool:
    """Only model the explicit integer-CLI high-temperature rule shapes seen live."""
    if not isinstance(rule, str) or isinstance(max_temp, bool) or not isinstance(max_temp, int):
        raise MarketDataError('Cannot verify noninteger official climate maximum')
    matched = THRESHOLD.findall(rule)
    if len(matched) != 1:
        raise MarketDataError('Unsupported/ambiguous temperature threshold')
    low, high, less, greater = matched[0]
    if low and high:
        if int(low) > int(high):
            raise MarketDataError('Invalid temperature range')
        return int(low) <= max_temp <= int(high)
    return max_temp < int(less) if less else max_temp > int(greater)


def get_json(session: requests.Session, url: str, *, params: dict | None = None,
             headers: dict | None = None) -> dict:
    resp = session.get(url, params=params, headers=headers, timeout=12, allow_redirects=False)
    resp.raise_for_status()
    if not 200 <= resp.status_code < 300:
        raise MarketDataError('Unexpected external response status')
    result = resp.json()
    if not isinstance(result, dict):
        raise MarketDataError('Non-object external response')
    return result


def portal_station(session: requests.Session, city: str, cli: str, target: date) -> tuple[dict, dict]:
    """Use an already resolved report solely for station mapping; never peek at target day."""
    ref_day = target - timedelta(days=2)
    document = get_json(session, SOURCE_URL, params={'date': ref_day.isoformat()},
                        headers=TWC_HEADERS)
    if document.get('date') != ref_day.isoformat() or not isinstance(document.get('results'), list):
        raise MarketDataError('TWC portal date/schema mismatch')
    code = cli.removeprefix('CLI')
    matches = [row for row in document['results'] if isinstance(row, dict) and
               isinstance(row.get('station'), dict) and row['station'].get('cliId') == code]
    if len(matches) != 1:
        raise MarketDataError('TWC final report has no unique CLI station')
    row = matches[0]
    station, data = row['station'], row.get('data') or {}
    if (station.get('city') != city or station.get('timezone') != str(LOCAL_TZ)
            or not re.fullmatch(r'K[A-Z]{3}', str(station.get('icao', '')))
            or row.get('status') not in ('official', 'revised')
            or not isinstance(data, dict) or data.get('isOfficial') is not True
            or data.get('reportDate') != ref_day.isoformat()):
        raise MarketDataError('TWC station mapping or prior report not final')
    return station, document


def nws_forecast(session: requests.Session, station: dict, target: date, received: datetime,
                 receipt_fn=None) -> dict:
    icao = station['icao']
    site = get_json(session, f'{NWS_ROOT}/stations/{icao}', headers=NWS_HEADERS)
    props, geo = site.get('properties') or {}, site.get('geometry') or {}
    if props.get('stationIdentifier') != icao or geo.get('type') != 'Point':
        raise MarketDataError('NWS station identity/geometry mismatch')
    coords = geo.get('coordinates')
    if not isinstance(coords, list) or len(coords) < 2:
        raise MarketDataError('Missing NWS station coordinates')
    lon, lat = coords[:2]
    if not isinstance(lat, (float, int)) or not isinstance(lon, (float, int)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise MarketDataError('Invalid NWS station coordinates')
    # NWS redirects /points/40.78333,-73.96667 to its documented four-decimal
    # canonical /points/40.7833,-73.9667. Normalize the station-derived value
    # instead of following any unexpected HTTP redirect or changing host.
    point = get_json(session, f'{NWS_ROOT}/points/{round(lat, 4)},{round(lon, 4)}',
                     headers=NWS_HEADERS)
    url = (point.get('properties') or {}).get('forecastHourly')
    if not isinstance(url, str) or not url.startswith(f'{NWS_ROOT}/gridpoints/') or '?' in url:
        raise MarketDataError('Untrusted NWS forecast URL')
    document = get_json(session, url, headers=NWS_HEADERS)
    forecast_received_at = receipt_fn() if receipt_fn is not None else datetime.now(timezone.utc)
    forecast = document.get('properties') or {}
    generated = forecast.get('generatedAt')
    periods = forecast.get('periods')
    if (not isinstance(generated, str) or not isinstance(periods, list)
            or forecast_received_at < received or parse_stamp(generated) > forecast_received_at):
        raise MarketDataError('NWS forecast time absent or after decision')
    observed = {}
    for p in periods:
        if not isinstance(p, dict) or not isinstance(p.get('startTime'), str):
            raise MarketDataError('Malformed NWS forecast period')
        local = parse_stamp(p['startTime']).astimezone(LOCAL_TZ)
        if local.date() != target:
            continue
        temp = p.get('temperature')
        if p.get('temperatureUnit') != 'F' or isinstance(temp, bool) or not isinstance(temp, (int, float)) or not -150 <= temp <= 150:
            raise MarketDataError('Missing NWS hourly Fahrenheit forecast')
        if stamp(local) in observed:
            raise MarketDataError('Duplicate NWS hourly forecast period')
        observed[stamp(local)] = temp
    midnight = datetime(target.year, target.month, target.day, tzinfo=LOCAL_TZ)
    following = target + timedelta(days=1)
    next_midnight = datetime(following.year, following.month, following.day, tzinfo=LOCAL_TZ)
    expected = int((next_midnight.astimezone(timezone.utc) - midnight.astimezone(timezone.utc)).total_seconds() / 3600)
    if (len(observed) != expected or sorted(observed) !=
            [stamp(midnight.astimezone(timezone.utc) + timedelta(hours=h)) for h in range(expected)]):
        raise MarketDataError('Incomplete DST-aware NWS next-day hourly forecast')
    return {'station': site, 'point': point, 'forecast': document,
            'forecast_received_at_utc': stamp(forecast_received_at),
            'hourly_count': expected, 'uncalibrated_grid_max_f': max(observed.values()),
            'interpretation': 'uncalibrated NWS grid forecast proxy, not a TWC/CLI settlement probability'}


def observe(client: PublicMarketClient, twc: requests.Session, nws: requests.Session,
            target: date, now: datetime) -> dict:
    moment = cutoff(target)
    if not moment <= now <= moment + timedelta(seconds=120):
        raise ValueError('Outside immutable pre-event 120-second cutoff')
    series = client.get_series(SERIES)
    require_source(series.get('settlement_sources'))
    listed = client.get_markets(SERIES, status='open', limit=200)
    candidates = []
    for market in listed:
        if not isinstance(market, dict) or not isinstance(market.get('rules_primary'), str):
            continue
        hits = RULE.findall(market['rules_primary'])
        if len(hits) == 1 and datetime.strptime(hits[0][2], '%b %d, %Y').date() == target:
            candidates.append(market['event_ticker'])
    ids = set(candidates)
    if len(ids) != 1:
        raise MarketDataError('Expected exactly one open next-day KXHIGHNY event')
    event_id = ids.pop()
    event = client.get_event(event_id)
    require_source(event.get('settlement_sources'))
    markets = event.get('markets')
    if event.get('series_ticker') != SERIES or not isinstance(markets, list):
        raise MarketDataError('Wrong weather event/series')
    city, cli = rule_identity(markets, target)
    if {m['ticker'] for m in markets} != {m['ticker'] for m in listed if m.get('event_ticker') == event_id}:
        raise MarketDataError('Incomplete event market listing')
    fee_type, fee_mult = effective_fees(series, event)
    station, previous_report = portal_station(twc, city, cli, target)
    forecast = nws_forecast(nws, station, target, now)
    if datetime.now(timezone.utc) > moment + timedelta(seconds=120):
        raise MarketDataError('Source collection passed frozen cutoff before books')
    books = []
    for market in sorted(markets, key=lambda m: m['ticker']):
        before = datetime.now(timezone.utc)
        book = client.get_orderbook(market['ticker'], depth=1)
        after = datetime.now(timezone.utc)
        if before < moment or after > moment + timedelta(seconds=120):
            raise MarketDataError('Orderbook received outside frozen cutoff')
        q = quote_from_orderbook(book)
        quotes = None
        if q is not None:
            quotes = {'yes_ask': str(q.yes_ask), 'no_ask': str(q.no_ask),
                      'yes_ask_size_fp': str(q.yes_ask_size), 'no_ask_size_fp': str(q.no_ask_size),
                      'indicative_yes_taker_fee_ceiling': str(fee_estimate(q.yes_ask, fee_type, fee_mult, maker=False)),
                      'indicative_no_taker_fee_ceiling': str(fee_estimate(q.no_ask, fee_type, fee_mult, maker=False))}
        books.append({'ticker': market['ticker'], 'before_utc': stamp(before),
                      'after_utc': stamp(after), 'orderbook_fp': book, 'quote': quotes})
    return {'type': 'decision_observation', 'observed_at_utc': stamp(datetime.now(timezone.utc)),
            'target_date': target.isoformat(), 'cutoff_utc': stamp(moment),
            'series': series, 'event': {k: v for k, v in event.items() if k != 'markets'},
            'event_ticker': event_id, 'markets': sorted(markets, key=lambda m: m['ticker']),
            'station_from_prior_final_TWC_report': station,
            'previous_report_date': previous_report['date'], 'previous_report_source': previous_report.get('source'),
            'forecast': forecast, 'books': books,
            'fee_type': fee_type, 'fee_multiplier': str(fee_mult),
            'paper_orders': 0, 'real_orders': 0, 'real_fills': 0,
            'probability_model': None, 'projected_profit': None}


def label(client: PublicMarketClient, twc: requests.Session, decision: dict) -> dict | None:
    target = date.fromisoformat(decision['target_date'])
    if datetime.now(LOCAL_TZ).date() <= target:
        return None
    report = get_json(twc, SOURCE_URL, params={'date': target.isoformat()}, headers=TWC_HEADERS)
    if report.get('date') != target.isoformat() or not isinstance(report.get('results'), list):
        raise MarketDataError('TWC final report date/schema mismatch')
    cli = decision['station_from_prior_final_TWC_report']['cliId']
    matches = [row for row in report['results'] if isinstance(row, dict) and
               isinstance(row.get('station'), dict) and row['station'].get('cliId') == cli]
    if len(matches) != 1:
        return None
    row = matches[0]
    if (row.get('status') not in ('official', 'revised') or not isinstance(row.get('data'), dict)
            or row['data'].get('isOfficial') is not True or row['data'].get('reportDate') != target.isoformat()
            or row['station'].get('icao') != decision['station_from_prior_final_TWC_report']['icao']
            or isinstance(row['data'].get('maxTemp'), bool)
            or not isinstance(row['data'].get('maxTemp'), (int, float))):
        return None
    event = client.get_event(decision['event_ticker'])
    markets = event.get('markets')
    if (not isinstance(markets, list) or {m.get('ticker') for m in markets} !=
            {m['ticker'] for m in decision['markets']}):
        raise MarketDataError('Venue settlement market set changed')
    if any(m.get('status') not in ('settled', 'finalized') or
           m.get('settlement_value_dollars') is None for m in markets):
        return None
    max_temp = row['data']['maxTemp']
    if not isinstance(max_temp, int):
        raise MarketDataError('Official climate maximum must be an integer Fahrenheit value')
    for m in markets:
        original = next(x for x in decision['markets'] if x['ticker'] == m['ticker'])
        if m.get('rules_primary') != original.get('rules_primary'):
            raise MarketDataError('Binding venue settlement rule changed after cutoff')
        expected = rule_payout(original['rules_primary'], max_temp)
        try:
            paid = Decimal(str(m['settlement_value_dollars']))
        except (InvalidOperation, TypeError) as exc:
            raise MarketDataError('Invalid venue terminal payout') from exc
        if paid != Decimal(int(expected)) or m.get('result') != ('yes' if expected else 'no'):
            raise MarketDataError('TWC official final value disagrees with venue settlement')
    return {'type': 'source_and_venue_label', 'observed_at_utc': stamp(datetime.now(timezone.utc)),
            'target_date': target.isoformat(), 'event_ticker': decision['event_ticker'],
            'twc_report_url': f'{SOURCE_URL}?date={target.isoformat()}',
            'twc_station_row': row, 'twc_source': report.get('source'),
            'venue_settlements': [{k: m.get(k) for k in ('ticker','status','result',
                                   'settlement_value_dollars','settlement_ts')} for m in markets],
            'paper_orders': 0, 'real_orders': 0, 'real_fills': 0,
            'projected_profit': None}


def revision_source_snapshot(twc: requests.Session, day: str, cli: str) -> dict:
    """Archive the current public source row without pretending a changed row agrees with venue."""
    report = get_json(twc, SOURCE_URL, params={'date':day}, headers=TWC_HEADERS)
    if report.get('date') != day or not isinstance(report.get('results'), list):
        raise MarketDataError('TWC revision source date/schema mismatch')
    matches = [row for row in report['results'] if isinstance(row, dict) and
               isinstance(row.get('station'), dict) and row['station'].get('cliId') == cli]
    if len(matches) != 1:
        raise MarketDataError('TWC revised source station absent/ambiguous')
    return {'source':report.get('source'), 'row':matches[0]}


def append(stream, record: dict) -> None:
    stream.write(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
    stream.flush()
    os.fsync(stream.fileno())


def open_journal(path: Path):
    if path.is_symlink() or path.parent.is_symlink():
        raise PermissionError('Journal symlink forbidden')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_mode & 0o077:
        raise PermissionError('Journal directory is not private')
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    if os.fstat(fd).st_mode & 0o077:
        os.close(fd)
        raise PermissionError('Journal file is not private')
    return os.fdopen(fd, 'a', buffering=1)


def load_journal(path: Path) -> tuple[list[dict], dict[str, dict], set[str], bool]:
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not records or records[0].get('type') != 'study_start' or any(
        r.get('paper_orders') != 0 or r.get('real_orders') != 0 or r.get('real_fills') != 0
        for r in records):
        raise ValueError('Invalid read-only study registration/records')
    reg = records[0]
    if (reg.get('series') != SERIES or reg.get('first_target') != FIRST_TARGET.isoformat()
            or reg.get('last_target') != LAST_TARGET.isoformat()
            or reg.get('until_utc') != stamp(DEADLINE) or reg.get('cutoff_local') != '18:00 America/New_York'
            or sum(r.get('type') == 'study_start' for r in records) != 1):
        raise ValueError('Study configuration is not immutable')
    decisions, labels, ended = {}, set(), False
    for row in records[1:]:
        typ = row.get('type')
        if ended:
            raise ValueError('Unexpected record after study end')
        if typ in ('decision_observation','decision_error','decision_missed'):
            day = row.get('target_date')
            if day in decisions or day is None:
                raise ValueError('Duplicate/invalid daily decision')
            decisions[day] = row
        elif typ == 'source_and_venue_label':
            day = row.get('target_date')
            if day in labels or day not in decisions or decisions[day]['type'] != 'decision_observation':
                raise ValueError('Duplicate/unknown source/venue label')
            labels.add(day)
        elif typ == 'source_revision_or_disagreement':
            day = row.get('target_date')
            if day not in labels or day not in decisions:
                raise ValueError('Revision lacks an earlier confirmed source/venue label')
            labels.remove(day)
        elif typ == 'decision_attempt_error':
            day = row.get('target_date')
            if day in decisions or day is None:
                raise ValueError('Out-of-window or invalid attempt error')
        elif typ == 'study_end':
            ended = True
        elif typ != 'label_error':
            raise ValueError('Unexpected study record type')
    return records, decisions, labels, ended


def run(*, journal: Path, public: PublicMarketClient | None = None,
        twc: requests.Session | None = None, nws: requests.Session | None = None,
        now_fn=lambda: datetime.now(timezone.utc), sleep=time.sleep) -> dict:
    if not isinstance(journal, Path):
        raise TypeError('Journal path must be pathlib.Path')
    with open_journal(journal) as out:
        fcntl.flock(out.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if journal.stat().st_size:
            records, decisions, labels, ended = load_journal(journal)
        else:
            append(out, {'type':'study_start', 'observed_at_utc':stamp(now_fn()),
                         'series':SERIES, 'first_target':FIRST_TARGET.isoformat(),
                         'last_target':LAST_TARGET.isoformat(), 'until_utc':stamp(DEADLINE),
                         'cutoff_local':'18:00 America/New_York',
                         'paper_orders':0,'real_orders':0,'real_fills':0})
            records, decisions, labels, ended = load_journal(journal)
        if ended:
            return {'already_finished':True, 'decisions':len(decisions), 'labels':len(labels)}
        public, twc, nws = public or PublicMarketClient(), twc or requests.Session(), nws or requests.Session()
        checks = 0
        while now_fn() < DEADLINE:
            now = now_fn()
            for offset in range((LAST_TARGET-FIRST_TARGET).days+1):
                target = FIRST_TARGET+timedelta(days=offset)
                key = target.isoformat()
                if key not in decisions:
                    c = cutoff(target)
                    if c <= now <= c+timedelta(seconds=120):
                        try:
                            row = observe(public, twc, nws, target, now)
                        except Exception as exc:
                            failure={'type':'decision_attempt_error','observed_at_utc':stamp(now_fn()),
                                     'target_date':key,'reason':f'{type(exc).__name__}: {str(exc)[:180]}',
                                     'paper_orders':0,'real_orders':0,'real_fills':0}
                            append(out,failure)
                            print(f'weather_attempt_error utc={stamp(now_fn())} target={key} '
                                  f'reason={failure["reason"]} orders=0',flush=True)
                        else:
                            append(out,row);decisions[key]=row
                            print(f'weather_decision utc={stamp(now_fn())} target={key} '
                                  f'type={row["type"]} orders=0',flush=True)
                    elif now > c+timedelta(seconds=120):
                        attempted = any(r.get('type') == 'decision_attempt_error' and
                                        r.get('target_date') == key for r in records)
                        # The bounded journal may contain new attempts since startup.
                        if not attempted:
                            with journal.open() as journal_reader:
                                attempted = any('"type":"decision_attempt_error"' in line and
                                                f'"target_date":"{key}"' in line for line in journal_reader)
                        row={'type':'decision_missed','observed_at_utc':stamp(now_fn()),
                             'target_date':key,'reason':'missed frozen 120-second cutoff',
                             'paper_orders':0,'real_orders':0,'real_fills':0}
                        if attempted:
                            row['type']='decision_error'
                            row['reason']='all source attempts failed during frozen 120-second cutoff'
                        append(out,row);decisions[key]=row
                if key in decisions and decisions[key]['type']=='decision_observation':
                    # Avoid later final-data leakage into the date's captured book/forecast.
                    # Revisit successful labels daily until the registered tail;
                    # revisions invalidate them instead of being silently lost.
                    original_label = next((r for r in reversed(records) if
                                           r.get('type') == 'source_and_venue_label' and
                                           r.get('target_date') == key), None)
                    if (now.astimezone(LOCAL_TZ).date()>target and
                            ((key not in labels and original_label is None and checks%180==0) or
                             (key in labels and checks%1440==0))):
                        try:
                            resolved=label(public, twc, decisions[key])
                            if resolved is not None and key not in labels:
                                append(out,resolved);labels.add(key)
                                records.append(resolved)
                                print(f'weather_label utc={stamp(now_fn())} target={key} source_and_venue_verified=True',flush=True)
                            elif key in labels:
                                old = (original_label.get('twc_station_row'),
                                       original_label.get('venue_settlements'))
                                new = ((resolved or {}).get('twc_station_row'),
                                       (resolved or {}).get('venue_settlements'))
                                if old != new:
                                    try:
                                        source_snapshot = revision_source_snapshot(
                                            twc,key,decisions[key]['station_from_prior_final_TWC_report']['cliId'])
                                    except Exception as source_exc:
                                        source_snapshot = {'unavailable':f'{type(source_exc).__name__}: {str(source_exc)[:120]}'}
                                    revision={'type':'source_revision_or_disagreement',
                                              'observed_at_utc':stamp(now_fn()),
                                              'target_date':key,'previous_label':original_label,
                                              'new_label_or_null':resolved,
                                              'current_source_snapshot':source_snapshot,
                                              'reason':'Previously confirmed source/venue observation changed or became nonfinal',
                                              'paper_orders':0,'real_orders':0,'real_fills':0}
                                    append(out,revision);records.append(revision);labels.remove(key)
                                    print(f'weather_revision utc={stamp(now_fn())} target={key} label_unresolved=True',flush=True)
                        except Exception as exc:
                            reason=f'{type(exc).__name__}: {str(exc)[:160]}'
                            if key in labels and ('disagrees with venue settlement' in reason or
                                                   'Venue settlement market set changed' in reason or
                                                   'rule changed' in reason):
                                try:
                                    source_snapshot = revision_source_snapshot(
                                        twc,key,decisions[key]['station_from_prior_final_TWC_report']['cliId'])
                                except Exception as source_exc:
                                    source_snapshot = {'unavailable':f'{type(source_exc).__name__}: {str(source_exc)[:120]}'}
                                revision={'type':'source_revision_or_disagreement',
                                          'observed_at_utc':stamp(now_fn()),'target_date':key,
                                          'previous_label':original_label,'new_label_or_null':None,
                                          'current_source_snapshot':source_snapshot,
                                          'reason':reason,'paper_orders':0,'real_orders':0,'real_fills':0}
                                append(out,revision);records.append(revision);labels.remove(key)
                            else:
                                append(out,{'type':'label_error','observed_at_utc':stamp(now_fn()),
                                            'target_date':key,'reason':reason,
                                            'paper_orders':0,'real_orders':0,'real_fills':0})
            checks+=1
            if checks%60==0:
                print(f'weather_progress utc={stamp(now_fn())} checks={checks} '
                      f'decisions={len(decisions)} labels={len(labels)} orders=0',flush=True)
            remaining = [(cutoff(FIRST_TARGET + timedelta(days=i)) - now_fn()).total_seconds()
                         for i in range((LAST_TARGET-FIRST_TARGET).days+1)
                         if (FIRST_TARGET + timedelta(days=i)).isoformat() not in decisions]
            nearest = min((x for x in remaining if x > 0), default=60.0)
            in_window = any(-120 <= x <= 0 for x in remaining)
            sleep(5.0 if in_window else min(60.0, max(0.2, nearest)))
        append(out, {'type':'study_end','observed_at_utc':stamp(now_fn()),
                     'decisions':len(decisions),'labels':len(labels),
                     'paper_orders':0,'real_orders':0,'real_fills':0})
        return {'decisions':len(decisions),'labels':len(labels),'real_orders':0}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    try:
        print('weather_study',run(journal=args.output),flush=True)
        return 0
    except Exception as exc:
        print(f'weather_study_failed {type(exc).__name__}: {str(exc)[:180]}',file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
