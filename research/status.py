"""Print compact V11 research-ledger counts; no network and no exchange mutation."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 local research ledger status")
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    args = parser.parse_args()
    conn = sqlite3.connect(args.database)
    tables = [
        "observations", "signals", "paper_orders", "paper_fills", "settlements",
        "mlb_historical_states", "kalshi_historical_markets", "kalshi_historical_candles",
    ]
    result = {table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}
    date_range = conn.execute("SELECT MIN(game_date), MAX(game_date) FROM mlb_historical_states").fetchone()
    result["mlb_historical_date_range"] = {"start": date_range[0], "end": date_range[1]}
    monthly = conn.execute(
        "SELECT substr(game_date, 1, 7) AS month, COUNT(*) FROM mlb_historical_states GROUP BY month ORDER BY month"
    ).fetchall()
    result["mlb_historical_states_by_month"] = {row[0]: int(row[1]) for row in monthly}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
