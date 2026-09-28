"""Inspect Kalshi's effective API tier via a signed GET; never sends orders."""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from account_preflight import secure_config
from core.kalshi_client import KalshiClient


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=Path('config.json'))
    p.add_argument('--output', type=Path, default=Path('logs/account_limits.json'))
    args = p.parse_args()
    try:
        client = KalshiClient(secure_config(args.config))
        if client.private_key is None:
            raise RuntimeError('Private signing key not loaded')
        result = {'checked_at': datetime.now(timezone.utc).isoformat(),
                  **client.get_api_limits(), 'exchange_writes': 0}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.is_symlink() or (args.output.exists() and
                stat.S_IMODE(args.output.stat().st_mode) & 0o077):
            raise PermissionError('Existing API tier report must be private')
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC |
                               os.O_NOFOLLOW, 0o600), 'w', encoding='utf-8') as output:
            json.dump(result, output, indent=2)
            output.write('\n')
        print('Effective Kalshi tier:', result['usage_tier'],
              '| read/write refill tokens per second:', result['read']['refill_rate'],
              result['write']['refill_rate'], '| exchange writes: 0')
        return 0
    except Exception as exc:
        print(f'API tier check stopped: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
