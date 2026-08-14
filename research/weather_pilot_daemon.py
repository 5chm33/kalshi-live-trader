"""Persistent paper-only weather pilot collector; contains no order capability."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.run_mlb_paper import load_config
from research.store import ResearchStore
from research.weather_pilot import run_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper-only settlement-mapped weather pilot")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--interval-seconds", type=int, default=1800)
    args = parser.parse_args()
    if args.interval_seconds < 300:
        raise ValueError("weather pilot interval must be at least 300 seconds")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api_config, config = load_config(args.config)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    store = ResearchStore(args.database)
    logging.info("paper-only weather pilot daemon started; no exchange mutation client exists")
    while True:
        started = time.monotonic()
        try:
            logging.info("weather_pilot=%s", run_cycle(client, store))
        except Exception as exc:
            logging.exception("paper-only weather cycle failed: %s", exc)
        time.sleep(max(0.0, args.interval_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
