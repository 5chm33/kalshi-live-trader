"""Reconcile a local journal against authenticated Kalshi GETs; never writes orders.

An absent order, missing fill, unverified position, or exchange read failure
blocks new entries. A submitted order is never re-submitted on a timeout.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from account_preflight import secure_config, strict_decimal
from core.execution_ledger import LedgerError, OrderLedger
from core.kalshi_client import KalshiClient


def reconcile(client: KalshiClient, ledger: OrderLedger) -> list[dict]:
    # Always verify cash and all pages of positions first. The balance is not
    # used as a fabricated initial bankroll for the local journal.
    client.get_account_snapshot()
    def venue_sizes() -> dict[str, Decimal]:
        sizes = {}
        for p in client.get_positions():
            ticker = p.get('ticker')
            if not ticker or ticker in sizes:
                raise LedgerError('Missing or duplicate venue position ticker')
            size = strict_decimal(p.get('position_fp'), 'position_fp')
            if size == 0:
                raise LedgerError('Unexpected zero position')
            sizes[ticker] = size
        return sizes

    venue_sizes()
    reports = []
    for intent in ledger.unresolved():
        client_id, ticker = intent['client_id'], intent['ticker']
        if intent['phase'] in {'prepared', 'partial_verified'}:
            reports.append(ledger.snapshot(client_id))
            continue
        orders = []
        for status in ('resting', 'executed', 'canceled'):
            orders.extend(order for order in client.get_orders_by_status(ticker, status)
                          if order.get('client_order_id') == client_id)
        orders.extend(order for order in client.get_historical_market_orders(ticker)
                      if order.get('client_order_id') == client_id)
        ids = {o.get('order_id') for o in orders}
        if len(orders) != 1 or len(ids) != 1 or None in ids:
            ledger.mark_uncertain(client_id, 'Order missing or ambiguous in venue GET')
            reports.append(ledger.snapshot(client_id))
            continue
        order = orders[0]
        ledger.attach_observed_order(client_id, order)
        fills = (client.get_market_fills(ticker)
                 + client.get_market_fills(ticker, historical=True))
        ours = [f for f in fills if f.get('order_id') == order['order_id']]
        if any(f.get('subaccount_number') != 0 for f in ours):
            ledger.mark_uncertain(client_id, 'Fill not attributable to primary subaccount')
            reports.append(ledger.snapshot(client_id))
            continue
        if len(ours) != len({f.get('fill_id') for f in ours}) or any(not f.get('fill_id') for f in ours):
            ledger.mark_uncertain(client_id, 'Duplicate or absent fill IDs across tiers')
            reports.append(ledger.snapshot(client_id))
            continue
        for fill in ours:
            ledger.record_fill(client_id, fill)
        latest = ledger.snapshot(client_id)
        if (Decimal(latest['confirmed_fill_count']) != Decimal(latest['exchange_fill_count']) or
                order['status'] not in {'executed', 'canceled'}):
            reports.append(latest)
            continue
        venue_size = venue_sizes().get(ticker, Decimal(0))
        if intent['action'] == 'buy':
            if Decimal(latest['confirmed_fill_count']) == 0 and venue_size == 0:
                ledger.record_verified_flat(client_id, order_terminal=True,
                                            exchange_position_size=venue_size)
        elif venue_size == 0:
            ledger.record_verified_flat(client_id, order_terminal=True,
                                        exchange_position_size=venue_size)
        else:
            ledger.record_partial_exit_terminal(client_id, order_terminal=True,
                                                verified_position_size=venue_size)
        reports.append(ledger.snapshot(client_id))
    return reports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config.json'))
    parser.add_argument('--ledger', type=Path, default=Path('logs/order_ledger.sqlite'))
    parser.add_argument('--output', type=Path, default=Path('logs/ledger_reconciliation.json'))
    args = parser.parse_args()
    try:
        client = KalshiClient(secure_config(args.config))
        with OrderLedger(args.ledger) as ledger:
            report = {'checked_at': datetime.now(timezone.utc).isoformat(),
                      'orders': reconcile(client, ledger), 'exchange_writes': 0}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.is_symlink() or (args.output.exists() and
                stat.S_IMODE(args.output.stat().st_mode) & 0o077):
            raise PermissionError('Existing reconciliation report must be private')
        with os.fdopen(os.open(args.output, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600),
                       'w', encoding='utf-8') as out:
            json.dump(report, out, indent=2)
            out.write('\n')
        print(f"Checked {len(report['orders'])} local intents against venue GETs. "
              "No exchange writes. Full result private under logs/.")
        return 0
    except Exception as exc:
        print(f'RECONCILIATION HALTED: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
