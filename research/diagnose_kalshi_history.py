"""Read-only diagnostic for official archived Kalshi MLB market history."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.run_mlb_paper import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 read-only historical Kalshi diagnostic")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    args = parser.parse_args()
    api_config, config = load_config(args.config)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    page = client.historical_markets("KXMLBGAME", limit=5)
    markets = page.get("markets", [])
    if not markets:
        raise RuntimeError("no archived KXMLBGAME markets returned")
    market = markets[0]
    # Keep minute candles inside a single market lifecycle window (the API
    # limits per-request candlestick output). Use the final two days pre-close
    # plus one hour after close where explicit timestamps are available.
    close_time = datetime.fromisoformat(str(market["close_time"]).replace("Z", "+00:00"))
    start = int(close_time.timestamp()) - 2 * 24 * 60 * 60
    end = int(close_time.timestamp()) + 60 * 60
    candles = client.historical_candlesticks(str(market["ticker"]), start, end, 1)
    print(json.dumps({
        "mode": "read_only_no_signal",
        "historical_market_count": len(markets),
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "yes_sub_title": market.get("yes_sub_title"),
        "close_time": market.get("close_time"),
        "result": market.get("result"),
        "candlestick_count": len(candles.get("candlesticks", [])),
        "candlestick_keys": sorted((candles.get("candlesticks") or [{}])[0].keys()),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
