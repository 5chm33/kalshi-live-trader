"""One-contract live execution-quality pilot. EXPERIMENTAL, NOT A PROFIT STRATEGY.

This program is never imported by main.py or the research collectors. It may
submit at most one new YES entry in its lifetime. It cannot use primary-account
funds, place resting entries, or infer success from an order acknowledgement.
The pre-funded, numbered subaccount limits total possible loss to its deposit.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from account_preflight import secure_config
from core.execution_ledger import LedgerError, OrderLedger
from core.fresh_book import fresh_confirmed_quote
from core.microstructure import _grid_check, effective_fees, fee_estimate, scheduled_start
from core.order_math import plan
from core.pilot_venue import MLB_SHARD, ScopedVenue, VenueError, money
from core.public_market import MarketDataError, PublicMarketClient, quote_from_orderbook

MAX_DEPOSIT = Decimal('2.00')
MAX_ENTRY = Decimal('0.50')
MAX_ENTRY_FEE = Decimal('0.04')
MAX_SPREAD = Decimal('0.04')
WINDOW = timedelta(hours=6)


def now_utc():
    return datetime.now(timezone.utc)


def safe_pilot_account(venue: ScopedVenue, ledger: OrderLedger, *, before_entry: bool) -> Decimal:
    cash = venue.cash()
    positions = venue.positions()
    resting = venue.orders(status='resting')
    if resting:
        raise VenueError('Unexpected resting order in dedicated subaccount')
    if before_entry:
        if cash < Decimal('0.55') or cash > MAX_DEPOSIT or positions:
            raise VenueError('Pilot account is not clean or is improperly funded')
        if ledger.db.execute('SELECT COUNT(*) FROM intents').fetchone()[0]:
            raise LedgerError('One-entry lifetime cap: journal already has an intent')
    return cash


def choose_candidate(public: PublicMarketClient, at: datetime) -> dict | None:
    """One independently displayed YES book, not a calibrated winning signal."""
    markets = public.get_markets('KXMLBGAME', status='open')
    grouped = {}
    for market in markets:
        event_id = market.get('event_ticker')
        if event_id and market.get('status') == 'active' and market.get('exchange_index') == MLB_SHARD:
            grouped.setdefault(event_id, []).append(market)
    series = public.get_series('KXMLBGAME')
    for event_id, pair in sorted(grouped.items()):
        if len(pair) != 2 or len({m.get('ticker') for m in pair}) != 2:
            continue
        try:
            first_pitch = scheduled_start(pair)
            if not timedelta(minutes=15) < first_pitch - at < WINDOW:
                continue
            event = public.get_event(event_id)
            if (not event.get('mutually_exclusive') or event.get('event_ticker') != event_id
                    or event.get('exchange_index') != MLB_SHARD):
                continue
            fee_type, multiplier = effective_fees(series, event)
            for market in sorted(pair, key=lambda m: m['ticker']):
                if market.get('is_provisional') is True:
                    continue
                stamp = time.monotonic()
                raw = public.get_orderbook(market['ticker'], depth=1)
                quote = quote_from_orderbook(raw)
                if quote is None or time.monotonic() - stamp > 3:
                    continue
                _grid_check(quote.yes_bid, market)
                _grid_check(quote.no_bid, market)
                _grid_check(quote.yes_ask, market)
                if not (Decimal('.35') <= quote.yes_ask <= MAX_ENTRY
                        and quote.yes_ask - quote.yes_bid <= MAX_SPREAD
                        and quote.yes_ask_size >= 1 and quote.no_ask_size >= 1):
                    continue
                reserve = fee_estimate(quote.yes_ask, fee_type, multiplier, maker=False)
                if reserve > MAX_ENTRY_FEE:
                    continue
                return {'ticker': market['ticker'], 'event': event_id,
                        'first_pitch': first_pitch, 'fee_type': fee_type,
                        'fee_multiplier': multiplier, 'market': market,
                        'observed_ask': quote.yes_ask,
                        'observed_bid': quote.yes_bid}
        except (MarketDataError, ValueError, KeyError):
            # A malformed individual event is NOT a reason to fabricate a quote.
            # Network errors propagate and stop the entire scan instead.
            continue
    return None


def refreshed_entry(venue: ScopedVenue, public: PublicMarketClient,
                    candidate: dict) -> tuple[Decimal, Decimal]:
    """Recheck venue status and executable book immediately before submit."""
    ticker = candidate['ticker']
    fresh_event = public.get_event(candidate['event'])
    fresh_series = public.get_series('KXMLBGAME')
    if (fresh_event.get('exchange_index') != MLB_SHARD or
            effective_fees(fresh_series, fresh_event) !=
            (candidate['fee_type'], candidate['fee_multiplier'])):
        raise VenueError('Candidate event shard or fee schedule changed')
    start = time.monotonic()
    market = public._get('/markets/' + ticker).get('market')
    if (not isinstance(market, dict) or market.get('ticker') != ticker
            or market.get('status') != 'active' or market.get('exchange_index') != MLB_SHARD):
        raise VenueError('Candidate market no longer active')
    quote = fresh_confirmed_quote(venue.client, public, ticker)
    if quote is None or time.monotonic() - start > 3:
        raise VenueError('Fresh two-sided book unavailable')
    _grid_check(quote.yes_bid, market)
    _grid_check(quote.no_bid, market)
    _grid_check(quote.yes_ask, market)
    if (quote.yes_ask_size < 1 or quote.no_ask_size < 1
            or not Decimal('.35') <= quote.yes_ask <= MAX_ENTRY
            or quote.yes_ask - quote.yes_bid > MAX_SPREAD
            or now_utc() >= candidate['first_pitch'] - timedelta(minutes=10)):
        raise VenueError('Entry price, depth, spread, or pregame window changed')
    fee = fee_estimate(quote.yes_ask, candidate['fee_type'], candidate['fee_multiplier'], maker=False)
    if fee > MAX_ENTRY_FEE:
        raise VenueError('Entry fee reserve exceeded')
    return quote.yes_ask, fee


def _position_size(venue: ScopedVenue, ticker: str) -> Decimal:
    positions = venue.positions()
    if len(positions) > 1 or any(p['ticker'] != ticker for p in positions):
        raise VenueError('Unexpected position in isolated account')
    return money(positions[0]['position_fp'], 'position_fp') if positions else Decimal(0)


def reconcile_one(venue: ScopedVenue, ledger: OrderLedger, client_id: str) -> dict:
    """Actual order, fill and position reads; missing state never becomes zero."""
    snapshot = ledger.snapshot(client_id)
    if snapshot['phase'] in ('prepared', 'verified_flat', 'partial_verified'):
        return snapshot
    ticker = snapshot['ticker']
    orders = [row for status in ('resting', 'executed', 'canceled')
              for row in venue.orders(status=status, ticker=ticker)
              if row.get('client_order_id') == client_id]
    archived_only = not orders
    if not orders:
        orders = [row for row in venue.archived_orders(ticker)
                  if row.get('client_order_id') == client_id]
    if len(orders) != 1:
        ledger.mark_uncertain(client_id, 'Absent or ambiguous client order ID; no write retry')
        raise VenueError('Cannot uniquely recover attempted order; manual reconciliation required')
    order = orders[0]
    ledger.attach_observed_order(client_id, order)
    if order['status'] == 'resting':
        if archived_only:
            raise VenueError('Archived resting order is not proof of a current cancellable order')
        venue.cancel_owned_resting(order, client_id)
        raise VenueError('Unexpected resting IOC canceled; wait for terminal venue status')
    fills = venue.fills(ticker, order['order_id'])
    observed = sum((money(f['count_fp'], 'fill count') for f in fills), Decimal(0))
    if observed < money(order['fill_count_fp'], 'order filled quantity'):
        archived = venue.archived_fills(ticker, order['order_id'])
        by_id = {f.get('fill_id'): f for f in fills}
        for old in archived:
            prior = by_id.get(old.get('fill_id'))
            if prior is not None and prior != old:
                raise VenueError('Live and archived fills disagree')
            by_id[old.get('fill_id')] = old
        fills = list(by_id.values())
    for fill in fills:
        ledger.record_fill(client_id, fill)
    current = ledger.snapshot(client_id)
    if money(current['confirmed_fill_count'], 'confirmed fills') != money(current['exchange_fill_count'], 'venue fills'):
        raise VenueError('Exchange fills are not yet fully visible; retry GET reconciliation only')
    size = _position_size(venue, ticker)
    action = ledger._row(client_id)['action']
    if action == 'buy':
        if money(current['confirmed_fill_count'], 'confirmed fills') == 0:
            if size != 0:
                raise VenueError('Unexplained isolated position after zero-fill entry')
            ledger.record_verified_flat(client_id, order_terminal=True, exchange_position_size=size)
        elif (size != money(current['confirmed_fill_count'], 'actual entry fills')
              or not Decimal(0) < size <= Decimal(1)):
            raise VenueError('Filled entry quantity does not match isolated venue inventory')
    else:
        if size == 0:
            ledger.record_verified_flat(client_id, order_terminal=True, exchange_position_size=size)
        else:
            ledger.record_partial_exit_terminal(client_id, order_terminal=True,
                                                verified_position_size=size)
    return ledger.snapshot(client_id)


def submit_one(venue: ScopedVenue, ledger: OrderLedger, ticker: str, price: Decimal,
               *, action: str, quantity: Decimal | int = 1,
               verified_position_size: Decimal | None = None) -> str:
    if action == 'buy' and quantity != 1:
        raise LedgerError('The sole pilot entry must request exactly one contract')
    item = plan('yes', action, quantity, price)
    client_id = 'pilot-' + uuid4().hex
    ledger.prepare(client_id, ticker, item, verified_position_size=verified_position_size)
    payload = item.payload(ticker, client_id, reduce_only=(action == 'sell'),
                           subaccount=venue.subaccount, exchange_index=MLB_SHARD)
    ledger.begin_submit(client_id)  # durable BEFORE any network write
    try:
        ack = venue.submit_ioc(payload)  # exactly ONE POST
        ledger.record_ack(client_id, ack)
    except Exception as exc:
        ledger.mark_uncertain(client_id, f'Single {action} POST or ACK uncertain')
        raise VenueError(f'{action} submission uncertain; reconcile GET by client ID, never re-submit') from exc
    return client_id


def entry_cost(ledger: OrderLedger, client_id: str) -> Decimal:
    rows = ledger.db.execute('SELECT count, yes_price, fee FROM fills WHERE client_id=?',
                             (client_id,)).fetchall()
    if not rows or not 0 < ledger.filled_quantity(client_id) <= Decimal(1):
        raise LedgerError('Entry fills do not prove owned inventory of at most one contract')
    return sum((money(x['count'], 'fill count') * money(x['yes_price'], 'YES price')
                + money(x['fee'], 'actual entry fee') for x in rows), Decimal(0))


def exit_quote(venue: ScopedVenue, public: PublicMarketClient, ticker: str, minimum_age: bool,
               entry: Decimal, fee_type: str, multiplier: Decimal,
               remaining: Decimal) -> Decimal | None:
    market = public._get('/markets/' + ticker).get('market')
    if (not isinstance(market, dict) or market.get('status') != 'active'
            or market.get('exchange_index') != MLB_SHARD):
        return None
    started = time.monotonic()
    quote = fresh_confirmed_quote(venue.client, public, ticker)
    if quote is None or quote.no_ask_size < remaining or time.monotonic() - started > 3:
        return None
    _grid_check(quote.yes_bid, market)
    if quote.yes_bid < Decimal('0.01'):
        return None
    if not minimum_age:
        fee = fee_estimate(quote.yes_bid, fee_type, multiplier, maker=False)
        if quote.yes_bid - fee < entry + Decimal('0.01'):
            return None
    return quote.yes_bid


def run(venue: ScopedVenue, public: PublicMarketClient, ledger: OrderLedger,
        *, deadline: datetime, poll_seconds: int = 30) -> dict:
    if ledger.subaccount != venue.subaccount or deadline <= now_utc():
        raise ValueError('Wrong ledger account or expired pilot deadline')
    if not 5 <= poll_seconds <= 120:
        raise ValueError('Poll interval outside bounds')
    sent_entry = ledger.db.execute("SELECT client_id FROM intents WHERE action='buy'").fetchall()
    if len(sent_entry) > 1:
        raise LedgerError('Multiple entries in one-entry pilot')
    candidate = None
    while now_utc() < deadline:
        sent_entry = ledger.db.execute("SELECT client_id FROM intents WHERE action='buy'").fetchall()
        if not sent_entry:
            safe_pilot_account(venue, ledger, before_entry=True)
            candidate = choose_candidate(public, now_utc())
            if candidate is None:
                print('No depth-qualified pregame candidate; no trade.', flush=True)
                time.sleep(poll_seconds)
                continue
            try:
                price, fee = refreshed_entry(venue, public, candidate)
                if venue.cash() < price + fee:
                    raise VenueError('Insufficient confirmed subaccount cash for price plus fee')
            except (VenueError, MarketDataError) as exc:
                print(f'Candidate rejected before POST: {type(exc).__name__}', flush=True)
                time.sleep(poll_seconds)
                continue
            cid = submit_one(venue, ledger, candidate['ticker'], price, action='buy')
            print(f'Sent one capped IOC entry {cid} ticker {candidate["ticker"]}; awaiting actual venue GETs.', flush=True)
            continue
        entry_id = sent_entry[0]['client_id']
        entry = ledger.snapshot(entry_id)
        existing_exits = ledger.db.execute(
            "SELECT client_id FROM intents WHERE action='sell' ORDER BY created_at, client_id").fetchall()
        if entry['phase'] == 'prepared':
            raise LedgerError('Prepared intent after restart: no automatic entry retry')
        # An exit may already have reduced inventory between processes. Once its
        # parent entry has terminal, fill-complete evidence, reconcile the exit
        # first rather than demanding the former one-contract position still exist.
        terminal_parent = (entry['phase'] == 'reconcile' and existing_exits
                           and ledger._row(entry_id)['exchange_status'] in {'executed', 'canceled'}
                           and money(entry['exchange_fill_count'], 'entry venue count') ==
                           money(entry['confirmed_fill_count'], 'entry fill count')
                           and Decimal(0) < money(entry['confirmed_fill_count'], 'entry fills') <= 1)
        if entry['phase'] != 'verified_flat' and not terminal_parent:
            reconcile_one(venue, ledger, entry_id)
            entry = ledger.snapshot(entry_id)
        if entry['phase'] == 'verified_flat':
            if not existing_exits:
                return {'status': 'verified_zero_fill', 'actual_order_attempts': 1,
                        'realized_net_dollars': None}
            proceeds = sum((money(x['count'], 'sale count') * money(x['yes_price'], 'sale price')
                            - money(x['fee'], 'actual sale fee')
                            for x in ledger.db.execute("""SELECT f.* FROM fills f JOIN intents i
                                ON i.client_id=f.client_id WHERE i.action='sell'""")), Decimal(0))
            return {'status': 'verified_closed', 'actual_order_attempts': 1 + len(existing_exits),
                    'realized_net_dollars': str(proceeds - entry_cost(ledger, entry_id))}
        if (entry['phase'] != 'reconcile' or
                not Decimal(0) < money(entry['confirmed_fill_count'], 'entry fills') <= 1):
            time.sleep(poll_seconds)
            continue
        ticker = entry['ticker']
        exits = ledger.db.execute("SELECT client_id FROM intents WHERE action='sell' ORDER BY created_at, client_id").fetchall()
        for x in exits:
            phase = ledger.snapshot(x['client_id'])['phase']
            if phase not in {'partial_verified', 'verified_flat'}:
                reconcile_one(venue, ledger, x['client_id'])
        if ledger.snapshot(entry_id)['phase'] == 'verified_flat':
            proceeds = sum((money(x['count'], 'sale count') * money(x['yes_price'], 'sale price')
                            - money(x['fee'], 'actual sale fee')
                            for x in ledger.db.execute("""SELECT f.* FROM fills f JOIN intents i
                                ON i.client_id=f.client_id WHERE i.action='sell'""")), Decimal(0))
            return {'status': 'verified_closed', 'actual_order_attempts': 1 + len(exits),
                    'realized_net_dollars': str(proceeds - entry_cost(ledger, entry_id))}
        remaining = (money(entry['confirmed_fill_count'], 'entry fills') - sum(
            (ledger.filled_quantity(x['client_id']) for x in exits), Decimal(0)))
        if not 0 < remaining <= 1 or _position_size(venue, ticker) != remaining:
            raise VenueError('Bot-owned residual one-contract holding cannot be verified')
        if venue.orders(status='resting'):
            raise VenueError('Unexpected resting order in isolated account before exit')
        if len(exits) >= 3:
            return {'status': 'open_holding_after_three_verified_exit_attempts',
                    'actual_entry_fills': str(money(entry['confirmed_fill_count'], 'entry fills')),
                    'remaining_contracts': str(remaining), 'realized_net_dollars': None}
        if exits and ledger.snapshot(exits[-1]['client_id'])['phase'] != 'partial_verified':
            time.sleep(poll_seconds)
            continue
        submitted = ledger._row(entry_id)['submitted_at']
        if not submitted:
            raise LedgerError('Missing persisted order attempt time')
        age = now_utc() - datetime.fromisoformat(submitted).replace(tzinfo=timezone.utc)
        # Within ten minutes, exit only if an actual best bid covers both fees
        # plus one cent; after ten minutes reduce-only at the fresh best bid.
        if age < timedelta(minutes=1):
            time.sleep(poll_seconds)
            continue
        # Never assume a fee schedule from one market applies to another:
        # fetch the venue series and exact event override on each decision.
        series = public.get_series('KXMLBGAME')
        event_id = ticker.rsplit('-', 1)[0]
        event = public.get_event(event_id)
        typ, mult = effective_fees(series, event)
        bid = exit_quote(venue, public, ticker, age >= timedelta(minutes=10),
                         entry_cost(ledger, entry_id) / money(entry['confirmed_fill_count'], 'entry fills'),
                         typ, mult, remaining)
        if bid is not None:
            submit_one(venue, ledger, ticker, bid, action='sell', quantity=remaining,
                       verified_position_size=remaining)
            print('Sent one reduce-only exit IOC at observed YES bid; awaiting GET reconciliation.', flush=True)
        else:
            print('Holding capped one-contract position: no eligible fresh exit bid.', flush=True)
        time.sleep(poll_seconds)
    return {'status': 'deadline_reached_verify_subaccount_position_manually',
            'actual_entry_attempts': len(sent_entry), 'realized_net_dollars': None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--subaccount', type=int, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--deadline-utc', required=True, help='ISO8601 UTC, <= 24 hours from now')
    parser.add_argument('--execute', action='store_true', help='Explicitly permit capped real orders')
    args = parser.parse_args()
    if not args.execute:
        print('LIVE PILOT DISABLED: --execute required', file=sys.stderr)
        return 2
    try:
        deadline = datetime.fromisoformat(args.deadline_utc.replace('Z', '+00:00'))
        if deadline.tzinfo is None or not now_utc() < deadline <= now_utc() + timedelta(hours=24):
            raise ValueError('Deadline must be within the next 24 hours (UTC)')
        config = secure_config(args.config)
        venue = ScopedVenue(config, args.subaccount)
        public = PublicMarketClient()
        with OrderLedger(args.ledger, subaccount=args.subaccount, max_entry_attempts_per_day=1) as ledger:
            result = run(venue, public, ledger, deadline=deadline)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        print(f'PILOT HALTED (DO NOT RESUBMIT): {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
