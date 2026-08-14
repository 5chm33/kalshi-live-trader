"""Backfill bounded completed MLB game-state data into the V11 research ledger."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mlb_history import MLBHistoricalCollector
from research.store import ResearchStore


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 official MLB history backfill")
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--max-games-per-day", type=int, default=20)
    parser.add_argument("--sleep-seconds", type=float, default=0.0, help="courteous delay between completed games")
    args = parser.parse_args()
    if args.end < args.start or args.max_games_per_day <= 0 or args.sleep_seconds < 0:
        raise ValueError("invalid date range, max-games-per-day, or sleep-seconds")

    collector = MLBHistoricalCollector(ResearchStore(args.database))
    current = args.start
    results = []
    while current <= args.end:
        ids = collector.game_ids(current)[:args.max_games_per_day]
        states = 0
        for game_pk in ids:
            states += collector.collect_game(game_pk, current)
            if args.sleep_seconds:
                time.sleep(args.sleep_seconds)
        results.append({"date": current.isoformat(), "games": len(ids), "states_seen": states, "stored_total": collector.store.historical_mlb_state_count()})
        current += timedelta(days=1)
    print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
