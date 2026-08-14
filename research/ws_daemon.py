"""Persistent paper-only WebSocket book-capture service for V11."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.capture_mlb_ws import capture_once


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper-only MLB WebSocket collector")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-updates", type=int, default=5000)
    args = parser.parse_args()
    if args.interval_seconds < 20:
        raise ValueError("interval must be at least 20 seconds")

    while True:
        started = time.monotonic()
        try:
            # Reserve a few seconds between connections for discovery and
            # reconnect backoff. If no games are live, capture_once returns
            # immediately and the daemon sleeps until the next cycle.
            summary = asyncio.run(
                capture_once(args.config, max_seconds=max(10, args.interval_seconds - 8), max_updates=args.max_updates)
            )
            logging.info("PAPER-ONLY websocket cycle=%s", json.dumps(summary, sort_keys=True))
        except KeyboardInterrupt:
            raise
        except Exception:
            logging.exception("PAPER-ONLY websocket cycle failed; no exchange mutation was attempted")
        time.sleep(max(0, args.interval_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
