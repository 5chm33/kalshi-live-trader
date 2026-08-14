"""Inspect one GET-only historical Kalshi markets page for pagination metadata."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.run_mlb_paper import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args()
    api_config, config = load_config(args.config)
    page = ReadOnlyKalshiClient(api_config, environment=config.environment).historical_markets("KXMLBGAME", args.limit)
    print(json.dumps({
        "keys": sorted(page.keys()), "market_count": len(page.get("markets", [])),
        "cursor": page.get("cursor"), "next_cursor": page.get("next_cursor"),
        "first_ticker": (page.get("markets") or [{}])[0].get("ticker"),
        "last_ticker": (page.get("markets") or [{}])[-1].get("ticker"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
