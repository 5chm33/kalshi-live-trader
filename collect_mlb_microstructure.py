"""Forward MLB quote-feasibility audit: public HTTPS GETs only, NEVER orders.

One distinct game is one trial. Serial 10-second book snapshots are not fills or
independent profit observations. The script is finite and survives service restarts
by resuming the same private JSONL journal and retaining its original start time.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.microstructure import effective_fees, paired_book, scheduled_start
from core.public_market import MarketDataError, PublicMarketClient

SERIES = "KXMLBGAME"
MAX_EVENTS = 120


def now_utc():
    return datetime.now(timezone.utc)


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def open_private_journal(path: Path):
    if path.is_symlink() or path.parent.is_symlink():
        raise PermissionError("Journal path cannot be a symlink")
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.parent.stat().st_mode & 0o077:
        raise PermissionError("Journal directory must be owner-only")
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    if os.fstat(fd).st_mode & 0o077:
        os.close(fd)
        raise PermissionError("Journal must be owner-only")
    return os.fdopen(fd, "a", buffering=1)


def emit(file, kind: str, **fields):
    file.write(json.dumps({"type": kind, "observed_at_utc": iso(now_utc()), **fields},
                          sort_keys=True, separators=(",", ":")) + "\n")
    file.flush()


def load_journal(path: Path):
    starts = []
    selected = {}
    settled = set()
    ended = False
    records = 0
    if not path.exists():
        return starts, selected, settled, ended
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise PermissionError("Existing journal is insecure")
    with path.open() as stream:
      for line in stream:
        if not line.strip():
            continue
        row = json.loads(line)
        records += 1
        if ended:
            raise ValueError("Rows appended after original study end")
        if records == 1 and row.get("type") != "study_start":
            raise ValueError("First journal row must be original registration")
        if row.get("type") == "study_start":
            if starts or selected or settled or row.get("series_ticker") != SERIES or row.get("max_events") != MAX_EVENTS or row.get("order_writes_enabled") is not False:
                raise ValueError("Invalid original study registration")
            start = datetime.fromisoformat(row["start_at_utc"].replace("Z", "+00:00"))
            deadline = datetime.fromisoformat(row["until_utc"].replace("Z", "+00:00"))
            if start.tzinfo is None or deadline.tzinfo is None or not start < deadline <= start + timedelta(days=7, minutes=2):
                raise ValueError("Invalid immutable study dates")
            starts.append(row)
        if row.get("type") == "event_selected":
            if not starts:
                raise ValueError("Event selected before study registration")
            if row["event_ticker"] in selected:
                raise ValueError("Duplicate event in persisted cohort")
            selected[row["event_ticker"]] = row["scheduled_start_utc"]
        if row.get("type") == "event_settlement":
            if not starts or row["event_ticker"] not in selected or row["event_ticker"] in settled:
                raise ValueError("Unselected or duplicated event settlement")
            settled.add(row["event_ticker"])
        if row.get("type") == "study_end":
            if not starts:
                raise ValueError("Unregistered study cannot end")
            ended = True
    if (records and not starts) or len(starts) > 1 or len(selected) > MAX_EVENTS:
        raise ValueError("Corrupt or duplicated study start/universe")
    return starts, selected, settled, ended


def event_markets(event):
    markets = event.get("markets")
    if (event.get("series_ticker") != SERIES or event.get("category") != "Sports"
            or event.get("product_metadata", {}).get("competition_scope") != "Game"
            or event.get("mutually_exclusive") is not True or not isinstance(markets, list)
            or len(markets) != 2):
        raise MarketDataError("Not exactly two mutually exclusive full-game winner markets")
    if len({m.get("ticker") for m in markets}) != 2:
        raise MarketDataError("Duplicate market ticker")
    start = scheduled_start(markets)
    return start, sorted(markets, key=lambda m: m["ticker"])


def discover(client, file, discovered_at, selected, series):
    """Choose only events seen at least an hour before their binding start."""
    rows = client.get_markets(series_ticker=SERIES, status="open", limit=200)
    event_ids = sorted({m.get("event_ticker") for m in rows if isinstance(m, dict)
                        and isinstance(m.get("event_ticker"), str)})
    candidates = []
    for ticker in event_ids:
        if ticker in selected or len(selected) >= MAX_EVENTS:
            continue
        try:
            event = client.get_event(ticker)
            start, markets = event_markets(event)
            if start < discovered_at + timedelta(minutes=60):
                continue  # never backfill a game without the prescribed hour
            effective_fees(series, event)
            candidates.append((start, ticker, event, markets))
        except (MarketDataError, TypeError, ValueError) as exc:
            emit(file, "event_excluded", event_ticker=ticker, reason=str(exc)[:160])
    for start, ticker, event, markets in sorted(candidates, key=lambda x: (x[0], x[1])):
        if len(selected) >= MAX_EVENTS:
            break
        selected[ticker] = iso(start)
        emit(file, "event_selected", event_ticker=ticker, scheduled_start_utc=iso(start),
             rules=[{k: m.get(k) for k in ("ticker", "rules_primary", "rules_secondary",
                 "price_ranges", "close_time", "expected_expiration_time", "occurrence_datetime")}
                    for m in markets], series_metadata=series,
             event_metadata={k: v for k, v in event.items() if k != "markets"})
    return selected


def scan_selected(client, file, selected, series, now):
    scanned = 0
    for ticker, start_text in selected.items():
        start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
        if not start - timedelta(minutes=60) <= now <= start + timedelta(minutes=1):
            continue
        try:
            event = client.get_event(ticker)
            current_start, markets = event_markets(event)
            if current_start != start:
                raise MarketDataError("Scheduled-time rule changed after selection")
            effective_fees(series, event)
            # Each request is an independent live public snapshot. No batch atomicity
            # and no guaranteed queue allocation; receipt times bound the skew.
            captured = []
            for market in markets:
                observed_before = now_utc()
                book = client.get_orderbook(market["ticker"], depth=1)
                observed_after = now_utc()
                captured.append({"ticker": market["ticker"], "before_utc": iso(observed_before),
                                 "after_utc": iso(observed_after), "book": book})
            result = paired_book(markets, [x["book"] for x in captured], series, event)
            emit(file, "book_snapshot", event_ticker=ticker, scheduled_start_utc=start_text,
                 sample_at_utc=captured[0]["before_utc"], books=captured,
                 statuses=[m.get("status") for m in markets],
                 current_market_metadata=[{k: m.get(k) for k in
                     ("ticker", "status", "close_time", "rules_primary", "price_ranges")}
                     for m in markets],
                 fee_type=event.get("fee_type_override") or series.get("fee_type"),
                 fee_multiplier=(event.get("fee_multiplier_override") if
                                 event.get("fee_multiplier_override") is not None else
                                 series.get("fee_multiplier")), conditional_quote=result,
                 real_orders=0, real_fills=0)
            scanned += 1
        except Exception as exc:
            emit(file, "book_error", event_ticker=ticker,
                 error_type=type(exc).__name__, reason=str(exc)[:160],
                 real_orders=0, real_fills=0)
    return scanned


def scan_settlements(client, file, selected, settled, now):
    for ticker, start_text in selected.items():
        start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
        if ticker in settled or not start + timedelta(hours=2) <= now <= start + timedelta(days=4):
            continue
        try:
            event = client.get_event(ticker)
            _, markets = event_markets(event)
            if any(m.get("status") != "settled" for m in markets):
                continue
            values = []
            for m in markets:
                value = m.get("settlement_value_dollars")
                if value is None:
                    raise MarketDataError("Settled market missing payout value")
                values.append({"ticker": m["ticker"], "result": m.get("result"),
                               "settlement_value_dollars": value, "settlement_ts": m.get("settlement_ts")})
            emit(file, "event_settlement", event_ticker=ticker, outcomes=values,
                 real_orders=0, real_fills=0)
            settled.add(ticker)
        except Exception as exc:
            emit(file, "settlement_error", event_ticker=ticker,
                 error_type=type(exc).__name__, reason=str(exc)[:160])


def collect(*, until: datetime, journal: Path, interval: float = 10.0,
            discover_interval: float = 300.0, client=None, sleep=time.sleep):
    if until.tzinfo is None or not 5 <= interval <= 60 or not 30 <= discover_interval <= 900:
        raise ValueError("Invalid UTC deadline or intervals")
    with open_private_journal(journal) as output:
        fcntl.flock(output.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        starts, selected, settled, ended = load_journal(journal)
        started = (datetime.fromisoformat(starts[0]["start_at_utc"].replace("Z", "+00:00"))
                   if starts else now_utc())
        if not starts:
            if until - started > timedelta(days=7, minutes=2):
                raise ValueError("Finite study may last no more than seven days")
            emit(output, "study_start", start_at_utc=iso(started), until_utc=iso(until),
                 series_ticker=SERIES, max_events=MAX_EVENTS,
                 prespecified_decision="nearest book_snapshot to first pitch minus 30m, within 5s",
                 trial_unit="distinct event_ticker", order_writes_enabled=False)
        if until - started > timedelta(days=7, minutes=2):
            raise ValueError("Study deadline extended after original start")
        if starts and starts[0].get("until_utc") != iso(until):
            raise ValueError("Study deadline differs from its immutable original record")
        if ended:
            return {"events_selected": len(selected), "cycles": 0,
                    "real_orders": 0, "already_completed": True}
        client = client or PublicMarketClient()
        last_discovery = 0.0
        last_settlement_check = 0.0
        series = None
        cycles = 0
        while now_utc() < until:
            t0 = time.monotonic()
            now = now_utc()
            try:
                if series is None or t0 - last_discovery >= discover_interval:
                    series = client.get_series(SERIES)
                    selected = discover(client, output, now, selected, series)
                    last_discovery = t0
                count = scan_selected(client, output, selected, series, now)
                if t0 - last_settlement_check >= 900:
                    scan_settlements(client, output, selected, settled, now)
                    last_settlement_check = t0
                cycles += 1
                if cycles % max(1, round(60 / interval)) == 0:
                    print(f'microstructure_progress utc={iso(now)} cycles={cycles} '
                          f'events={len(selected)} snapshots_last_cycle={count} '
                          'orders=0', flush=True)
            except Exception as exc:
                emit(output, "cycle_error", error_type=type(exc).__name__,
                     reason=str(exc)[:160], real_orders=0, real_fills=0)
            sleep(max(0.1, interval - (time.monotonic() - t0)))
        emit(output, "study_end", events_selected=len(selected), cycles=cycles,
             real_orders=0, real_fills=0)
    return {"events_selected": len(selected), "cycles": cycles, "real_orders": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--until-utc", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=10)
    args = parser.parse_args()
    try:
        until = datetime.fromisoformat(args.until_utc.replace("Z", "+00:00"))
        collect(until=until, journal=args.output, interval=args.interval_seconds)
    except Exception as exc:
        print(f"microstructure_failed: {type(exc).__name__}: {str(exc)[:160]}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
