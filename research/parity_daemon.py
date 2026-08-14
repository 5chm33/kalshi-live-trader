"""Persistent paper-only collector for structural Kalshi parity research."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.capture_binary_parity import run_cycle as run_binary
from research.capture_directional_parity import run_cycle as run_directional
from research.kalshi_readonly import ReadOnlyKalshiClient
from research.run_mlb_paper import load_config
from research.store import ResearchStore


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper-only structural parity daemon")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--max-markets", type=int, default=100)
    parser.add_argument("--max-events", type=int, default=50)
    args = parser.parse_args()
    if args.interval_seconds < 60:
        raise ValueError("interval-seconds must be at least 60 for the bounded research collector")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    api_config, config = load_config(args.config)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    store = ResearchStore(args.database)
    logging.info("paper-only parity daemon started; no exchange mutation client exists")
    while True:
        started = time.monotonic()
        try:
            binary = run_binary(client, store, max_markets=args.max_markets)
            directional = run_directional(client, store, max_events=args.max_events)
            logging.info("binary=%s directional=%s", binary, directional)
        except Exception as exc:
            logging.exception("paper-only parity cycle failed: %s", exc)
        time.sleep(max(0.0, args.interval_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
