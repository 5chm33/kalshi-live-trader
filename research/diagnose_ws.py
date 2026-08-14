"""Read-only Kalshi WebSocket order-book diagnostic for V11."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.kalshi_ws import KalshiMarketStream
from research.run_mlb_paper import load_config
from research.ws_book import WebSocketBookSynchronizer


async def diagnose(config_file: Path, ticker: str | None) -> dict[str, object]:
    api_config, config = load_config(config_file)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    chosen = ticker
    if not chosen:
        markets = client.markets("KXMLBGAME", limit=100).get("markets", [])
        chosen = next((str(item.get("ticker")) for item in markets if item.get("ticker")), None)
    if not chosen:
        raise RuntimeError("no open KXMLBGAME market found for WebSocket diagnostic")

    stream = KalshiMarketStream(client, environment=config.environment)
    sync = WebSocketBookSynchronizer()
    async for event in stream.events(["orderbook_delta"], [chosen]):
        book = sync.apply(event)
        if book is None:
            continue
        return {
            "mode": "read_only_no_signal",
            "ticker": chosen,
            "message_type": event.get("type"),
            "best_yes_bid": str(book.best_yes_bid) if book.best_yes_bid is not None else None,
            "best_yes_ask": str(book.best_yes_ask) if book.best_yes_ask is not None else None,
            "yes_levels": len(book.yes_bids),
            "no_levels": len(book.no_bids),
            "payload_sha256": book.stamp.payload_sha256,
        }
    raise RuntimeError("WebSocket stream ended without an order-book snapshot")


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 read-only WebSocket diagnostic")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--ticker")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(diagnose(args.config, args.ticker)), sort_keys=True))


if __name__ == "__main__":
    main()
