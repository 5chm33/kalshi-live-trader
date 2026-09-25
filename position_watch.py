"""One-shot, GET-only per-position market-value check; never sends an order.

Only emits P&L if all live-tier fills reconcile exactly to an existing venue
position and a fresh executable book has enough depth to liquidate it. Older
fills may need historical endpoints; in that case output is unavailable,
never zero or a fabricated return.
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
from core.kalshi_client import KalshiClient
from core.position_valuation import value_position
from core.public_market import PublicMarketClient, quote_from_orderbook
from main import estimated_taker_fee


def inspect_positions(client: KalshiClient, public: PublicMarketClient) -> list[dict]:
    positions = client.get_positions()
    results = []
    for position in positions:
        ticker = position.get('ticker')
        if not ticker:
            raise ValueError('Position without ticker')
        held = strict_decimal(position.get('position_fp'), 'position_fp')
        if held == 0:
            raise ValueError('Zero holding in nonzero-position response')
        outcome = 'yes' if held > 0 else 'no'
        row = {'ticker': ticker, 'outcome': outcome, 'subaccount': 0,
               'venue_position_fp': str(held)}
        try:
            fills = client.get_market_fills(ticker) + client.get_market_fills(ticker, historical=True)
            if len({f.get('fill_id') for f in fills}) != len(fills):
                raise ValueError('Duplicate or missing live/historical fill ID')
            if any('subaccount_number' not in f for f in fills):
                raise ValueError('Fill lacks subaccount identity')
            fills = [f for f in fills if f['subaccount_number'] == 0]
            entries, exits = [], []
            for fill in fills:
                if (fill.get('ticker') or fill.get('market_ticker')) != ticker:
                    raise ValueError('Fill ticker mismatch')
                side = fill.get('book_side')
                if side not in {'bid', 'ask'}:
                    raise ValueError('Fill missing canonical book side')
                (entries if (side == 'bid') == (outcome == 'yes') else exits).append(fill)
            bought = sum((strict_decimal(x.get('count_fp'), 'count_fp') for x in entries), Decimal(0))
            sold = sum((strict_decimal(x.get('count_fp'), 'count_fp') for x in exits), Decimal(0))
            if bought - sold != abs(held):
                raise ValueError('Recent fills do not reconcile to venue position; historical fills may be required')
            if exits or not entries:
                raise ValueError('Complex prior position history needs full ordered cost-basis reconstruction')
            book = public.get_orderbook(ticker)
            observed_at = datetime.now(timezone.utc)
            quote = quote_from_orderbook(book)
            if quote is None:
                raise ValueError('No executable two-sided orderbook')
            if abs(held) != int(abs(held)):
                raise ValueError('Partial-contract fee estimate needs series-specific handling')
            bid = quote.yes_bid if outcome == 'yes' else quote.no_bid
            # An estimated future exit fee is not charged yet; distinguish it
            # from authoritative fees already present in confirmed fills.
            future_fee = estimated_taker_fee(bid, count=int(abs(held)))
            valuation = value_position(outcome=outcome, entry_fills=entries,
                exit_fills=exits, quote=quote, observed_at=observed_at,
                now=datetime.now(timezone.utc), estimated_exit_fee=future_fee)
            row.update({'status': 'valued', 'as_of': observed_at.isoformat(),
                'remaining': str(valuation.remaining_count),
                'executable_bid': str(valuation.conservative_bid),
                'realized_pnl_from_confirmed_fills': f'{valuation.realized_pnl:.4f}',
                'estimated_unrealized_liquidation_pnl': f'{valuation.estimated_unrealized_pnl:.4f}',
                'estimated_total_pnl': f'{valuation.estimated_total_pnl:.4f}',
                'note': 'Top-of-book and estimated future fee; not a guaranteed sale price.'})
        except Exception as exc:
            row.update({'status': 'unavailable', 'reason': str(exc)[:180]})
        results.append(row)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config.json'))
    parser.add_argument('--output', type=Path, default=Path('logs/position_watch.json'))
    args = parser.parse_args()
    try:
        client = KalshiClient(secure_config(args.config))
        result = {'observed_at': datetime.now(timezone.utc).isoformat(),
                  'positions': inspect_positions(client, PublicMarketClient()),
                  'orders_submitted': 0}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.is_symlink() or (args.output.exists() and
                stat.S_IMODE(args.output.stat().st_mode) & 0o077):
            raise PermissionError('Position report must be private and not a symlink')
        with os.fdopen(os.open(args.output, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, 0o600),
                       'w', encoding='utf-8') as output:
            json.dump(result, output, indent=2)
            output.write('\n')
        print(f"Checked {len(result['positions'])} positions via real fills and book. "
              f"Valued {sum(p['status']=='valued' for p in result['positions'])}; "
              f"unavailable {sum(p['status']!='valued' for p in result['positions'])}.")
        print(f"Private report: {args.output.resolve()}; no orders placed.")
        return 0
    except Exception as exc:
        print(f'Position check stopped: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
