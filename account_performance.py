"""Read-only account-level realized P&L diagnostic, not a bot backtest.

Queries live and historical market positions. Historical per-market P&L is
reported as returned by Kalshi, without guessing whether a fee is already
included. It is NOT a validated strategy-level return or a fill-level ledger.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

from account_preflight import secure_config, strict_decimal
from core.kalshi_client import KalshiClient


def paged(client: KalshiClient, path: str, field: str) -> list[dict]:
    records = []
    cursor = None
    seen = set()
    for _ in range(100):
        joiner = '&' if '?' in path else '?'
        query = path + (joiner + 'cursor=' + quote(str(cursor), safe='') if cursor else '')
        payload = client._request('GET', query)
        if payload is None or not isinstance(payload.get(field), list):
            raise RuntimeError(f'Cannot verify complete {field} history')
        records.extend(payload[field])
        cursor = payload.get('cursor')
        if not cursor:
            return records
        if cursor in seen:
            raise RuntimeError(f'{field} pagination loop')
        seen.add(cursor)
    raise RuntimeError(f'{field} history exceeds 100 pages; no partial result')


def summarize(client: KalshiClient) -> dict:
    recent = paged(client, '/portfolio/positions?count_filter=total_traded&limit=200', 'market_positions')
    historical = paged(client, '/historical/positions?limit=200', 'market_positions')
    historical_tickers = set()
    wins = losses = even = 0
    pnl = fees = Decimal(0)
    for pos in historical:
        ticker = pos.get('ticker')
        if not ticker or ticker in historical_tickers:
            raise ValueError('Historical market ticker missing or duplicated')
        historical_tickers.add(ticker)
        value = strict_decimal(pos.get('realized_pnl_dollars'), 'realized_pnl_dollars')
        fee = strict_decimal(pos.get('fees_paid_dollars'), 'fees_paid_dollars')
        if fee < 0:
            raise ValueError('Negative exchange fee in historical position')
        pnl += value
        fees += fee
        wins += value > 0
        losses += value < 0
        even += value == 0
    recent_tickers = set()
    open_count = 0
    for pos in recent:
        ticker = pos.get('ticker')
        if not ticker or ticker in recent_tickers or ticker in historical_tickers:
            raise ValueError('Live market ticker missing, duplicated, or overlaps archive')
        recent_tickers.add(ticker)
        open_count += strict_decimal(pos.get('position_fp'), 'position_fp') != 0
    resolved = wins + losses
    return {'checked_at': datetime.now(timezone.utc).isoformat(),
            'recent_traded_market_count': len(recent),
            'recent_open_market_count': open_count,
            'archived_market_count': len(historical),
            'archived_positive_pnl_markets': wins,
            'archived_negative_pnl_markets': losses,
            'archived_flat_pnl_markets': even,
            'archived_reported_realized_pnl_dollars': str(pnl),
            'archived_reported_fees_paid_dollars': str(fees),
            'archived_nonflat_market_win_fraction': str(Decimal(wins) / resolved) if resolved else None,
            'bot_attribution': 'UNAVAILABLE: markets may include unrelated manual activity',
            'caveat': 'Archived markets only; recent trading and open positions omitted from P&L. Do not subtract fees again without confirming Kalshi field semantics.'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config.json'))
    parser.add_argument('--output', type=Path, default=Path('logs/account_performance.json'))
    args = parser.parse_args()
    try:
        client = KalshiClient(secure_config(args.config))
        result = summarize(client)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.is_symlink() or (args.output.exists() and
                stat.S_IMODE(args.output.stat().st_mode) & 0o077):
            raise PermissionError('Existing report must be private and not a symlink')
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600),
                       'w', encoding='utf-8') as output:
            json.dump(result, output, indent=2)
            output.write('\n')
        print(f"Account-wide archive: {result['archived_market_count']} markets; "
              f"reported realized P&L ${result['archived_reported_realized_pnl_dollars']}. "
              "Not bot-attributed or proof of future profitability.")
        return 0
    except Exception as exc:
        print(f'Performance snapshot stopped: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
