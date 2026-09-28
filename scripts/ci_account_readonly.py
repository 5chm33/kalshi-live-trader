"""Run only in a reviewed CI job with short-lived repository secrets.

No authenticated POST/DELETE is implemented. Stdout contains only a tier and
aggregate counts; never print the key, order identifiers, or account payloads.
"""
from __future__ import annotations

import os
import sys

from core.kalshi_client import KalshiClient


def check(client: KalshiClient) -> dict:
    if client.private_key is None:
        raise RuntimeError('Signing key was not loaded')
    tier = client.get_api_limits()
    account = client.get_account_snapshot()
    positions = client.get_positions()
    orders = client.get_resting_orders()
    if not isinstance(account.get('cash_dollars'), str):
        raise RuntimeError('Account snapshot incomplete')
    if any(not p.get('ticker') for p in positions):
        raise RuntimeError('Malformed primary position response')
    if any(not o.get('order_id') for o in orders):
        raise RuntimeError('Malformed resting order response')
    return {'effective_tier': tier['usage_tier'],
            'read_refill_tokens_per_second': tier['read']['refill_rate'],
            'write_refill_tokens_per_second': tier['write']['refill_rate'],
            'primary_open_position_count': len(positions),
            'resting_order_count': len(orders),
            'cash_field_present': True, 'exchange_writes': 0}


def main() -> int:
    key_id = os.environ.get('KALSHI_CI_KEY_ID')
    pem = os.environ.get('KALSHI_CI_PRIVATE_KEY')
    if not key_id or not pem:
        print('Read-only CI account check skipped: missing ephemeral secrets')
        return 0
    try:
        client = KalshiClient({'api_key': key_id, 'private_key_string': pem})
        result = check(client)
        for key, value in result.items():
            print(f'{key}={value}')
        return 0
    except Exception as exc:
        print(f'Read-only CI account check failed: {type(exc).__name__}: {str(exc)[:180]}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
