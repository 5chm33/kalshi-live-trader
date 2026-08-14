"""Diagnose strict historical MLB/Kalshi matching; no network and no exchange mutation."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mlb_matcher import team_code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--date", default="2026-06-04")
    args = parser.parse_args()
    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row
    state = conn.execute(
        """SELECT * FROM mlb_historical_states
           WHERE game_date = ? AND away_team IS NOT NULL AND home_team IS NOT NULL LIMIT 1""",
        (args.date,),
    ).fetchone()
    markets = conn.execute(
        "SELECT ticker, event_ticker, close_time, yes_sub_title FROM kalshi_historical_markets WHERE close_time LIKE ?",
        (args.date + "%",),
    ).fetchall()
    if state is None:
        print(json.dumps({"status": "no_state_for_date", "date": args.date, "markets_that_date": len(markets)}))
        return
    source = datetime.fromisoformat(str(state["source_at"]).replace("Z", "+00:00"))
    token = source.strftime("%y%b%d").upper()
    away = team_code(str(state["away_team"]))
    home = team_code(str(state["home_team"]))
    leader = home if bool(state["leader_is_home"]) else away
    candidates = [
        dict(market) for market in markets
        if str(market["ticker"]).rsplit("-", 1)[-1].upper() == leader
        and away in str(market["event_ticker"]).upper()
        and home in str(market["event_ticker"]).upper()
        and token in str(market["event_ticker"]).upper()
    ]
    print(json.dumps({
        "date": args.date, "state_source_at": state["source_at"], "date_token": token,
        "away_team": state["away_team"], "away_code": away,
        "home_team": state["home_team"], "home_code": home,
        "leader_code": leader, "markets_that_close_date": len(markets),
        "exact_candidates": candidates, "market_sample": [dict(market) for market in markets[:4]],
    }, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
