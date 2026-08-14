"""Capture time-aligned MLB Kalshi order-book observations via WebSocket.

This is a research collector. It discovers currently live MLB game-winner
contracts, listens only to authenticated public order-book data, validates
sequence continuity, and writes local observations. It has no order path.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.kalshi_ws import KalshiMarketStream
from research.mlb_feed import MLBFeed
from research.mlb_matcher import match_game_markets
from research.run_mlb_paper import load_config
from research.store import ResearchStore
from research.ws_book import SequenceGap, WebSocketBookSynchronizer

LOG = logging.getLogger("kalshi_research_v11.ws")


def _book_payload(book: Any) -> dict[str, Any]:
    return {
        "ticker": book.ticker,
        "yes_bids": [[str(level.price), str(level.quantity)] for level in book.yes_bids],
        "no_bids": [[str(level.price), str(level.quantity)] for level in book.no_bids],
        "best_yes_bid": str(book.best_yes_bid) if book.best_yes_bid is not None else None,
        "best_yes_ask": str(book.best_yes_ask) if book.best_yes_ask is not None else None,
        "best_no_bid": str(book.best_no_bid) if book.best_no_bid is not None else None,
        "best_no_ask": str(book.best_no_ask) if book.best_no_ask is not None else None,
    }


async def capture_once(config_file: Path, max_seconds: int, max_updates: int) -> dict[str, int]:
    api_config, config = load_config(config_file)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    store = ResearchStore(config.database_path)
    games = MLBFeed().live_games()
    markets = [item for item in client.markets("KXMLBGAME").get("markets", []) if isinstance(item, Mapping)]
    tickers = sorted({mapping.ticker for game in games for mapping in match_game_markets(game, markets)})
    summary = {"live_games": len(games), "matched_tickers": len(tickers), "book_updates": 0, "sequence_gaps": 0}
    if not tickers:
        return summary

    stream = KalshiMarketStream(client, environment=config.environment)
    synchronizer = WebSocketBookSynchronizer()
    deadline = time.monotonic() + max_seconds
    async for payload in stream.events(["orderbook_delta"], tickers):
        if time.monotonic() >= deadline or summary["book_updates"] >= max_updates:
            break
        try:
            book = synchronizer.apply(payload)
        except SequenceGap as error:
            # Do not treat the potentially stale book as valid. The next stream
            # reconnect/snapshot is the only permissible recovery.
            summary["sequence_gaps"] += 1
            LOG.warning("Discarded WebSocket book after sequence gap: %s", error)
            break
        if book is None:
            continue
        store.record_observation(book.stamp, "kalshi_ws_orderbook", book.ticker, _book_payload(book))
        summary["book_updates"] += 1
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper-only MLB WebSocket capture")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--max-seconds", type=int, default=60)
    parser.add_argument("--max-updates", type=int, default=500)
    args = parser.parse_args()
    if args.max_seconds <= 0 or args.max_updates <= 0:
        raise ValueError("max-seconds and max-updates must be positive")
    print(json.dumps(asyncio.run(capture_once(args.config, args.max_seconds, args.max_updates)), sort_keys=True))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
