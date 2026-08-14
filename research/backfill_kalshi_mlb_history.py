"""Collect bounded archived Kalshi MLB market/candlestick data into the V11 ledger."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.kalshi_history import KalshiHistoricalMLBCollector
from research.kalshi_readonly import ReadOnlyKalshiClient
from research.run_mlb_paper import load_config
from research.store import ResearchStore


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 read-only archived Kalshi MLB collector")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--max-markets", type=int, default=20)
    args = parser.parse_args()
    if args.max_pages <= 0 or args.max_markets <= 0:
        raise ValueError("max-pages and max-markets must be positive")
    api_config, config = load_config(args.config)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    summary = KalshiHistoricalMLBCollector(client, ResearchStore(args.database)).collect_markets(args.max_pages, args.max_markets)
    print(json.dumps({"mode": "read_only_no_signal", **summary}, sort_keys=True))


if __name__ == "__main__":
    main()
