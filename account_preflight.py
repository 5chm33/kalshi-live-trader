"""Authenticated read-only diagnostic; does not submit, modify, or cancel orders.

Provision config.json locally with mode 0600. Never commit it or publish the output.
This is only a state check; it does not make any strategy profitable or live-ready.
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

from core.kalshi_client import KalshiClient


def strict_decimal(value: object, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field}") from exc
    if not number.is_finite():
        raise ValueError(f"Invalid {field}")
    return number


def secure_config(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f"Private Kalshi config missing: {path}")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError("Config must be private (chmod 600); no group or other access")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict) or not cfg.get("api_key"):
        raise ValueError("Missing Kalshi API key ID")
    if not any(cfg.get(k) for k in ("private_key_string", "private_key", "private_key_path")):
        raise ValueError("Missing Kalshi signing key")
    for key_name in ("private_key_path", "private_key"):
        candidate = cfg.get(key_name)
        if candidate and not str(candidate).startswith("-----BEGIN"):
            pem = Path(candidate)
            if not pem.is_file() or stat.S_IMODE(pem.stat().st_mode) & 0o077:
                raise PermissionError("Private signing-key file must exist with mode 0600")
    return cfg


def inspect(client: KalshiClient) -> dict:
    if not client.private_key:
        raise RuntimeError("Kalshi private key not loaded")
    balance = client.get_account_snapshot()
    positions = client.get_positions()
    orders = client.get_resting_orders()
    fills = client.get_fills(limit=100)
    signed = []
    for pos in positions:
        ticker = pos.get("ticker")
        if not ticker:
            raise ValueError("Market position lacks ticker")
        size = strict_decimal(pos.get("position_fp"), "position_fp")
        if size == 0:
            raise ValueError("Nonzero-position response contains zero contracts")
        signed.append((ticker, str(size)))
    for order in orders:
        if not order.get("order_id") or not order.get("ticker"):
            raise ValueError("Resting order lacks id or ticker")
        if strict_decimal(order.get("remaining_count_fp"), "remaining_count_fp") <= 0:
            raise ValueError("Resting order has no valid remaining size")
    for fill in fills:
        if not fill.get("order_id") or not fill.get("fill_id"):
            raise ValueError("Fill response missing id")
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            **balance, "open_position_count": len(signed),
            "resting_order_count": len(orders), "recent_fill_count": len(fills),
            "position_subaccount": 0,
            "note_on_scope": "Positions are primary subaccount 0; other account GETs may cover a broader scope.",
            "position_sizes": signed,
            "trading_enabled": False,
            "note": "Read-only verification; these counts do not validate strategy or profitability."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--output", type=Path, default=Path("logs/account_preflight.json"))
    args = parser.parse_args()
    try:
        client = KalshiClient(secure_config(args.config))
        result = inspect(client)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.is_symlink() or (args.output.exists() and
                stat.S_IMODE(args.output.stat().st_mode) & 0o077):
            raise PermissionError("Existing account report must be private and not a symlink")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        with os.fdopen(os.open(args.output, flags, 0o600), "w", encoding="utf-8") as output:
            output.write(json.dumps(result, indent=2) + "\n")
        print(f"Read-only account check passed. Report: {args.output.resolve()}")
        print(f"Cash: ${result['cash_dollars']} | Open positions: {result['open_position_count']} | Resting orders: {result['resting_order_count']}")
        print("Live trading remains disabled. No orders were placed.")
        return 0
    except Exception as exc:
        print(f"Read-only account preflight stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
