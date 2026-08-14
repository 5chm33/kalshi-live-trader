"""Inspect one official MLB completed-game feed for calibration feature availability."""
from __future__ import annotations

import argparse
import json
from datetime import date

import requests

SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule/games/"
FEED = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=date.fromisoformat, default=date(2025, 6, 1))
    args = parser.parse_args()
    schedule = requests.get(SCHEDULE, params={"sportId": 1, "date": args.date.isoformat()}, timeout=20).json()
    game = next(item for day in schedule.get("dates", []) for item in day.get("games", []) if item.get("gamePk"))
    payload = requests.get(FEED.format(game_pk=game["gamePk"]), timeout=20).json()
    plays = payload.get("liveData", {}).get("plays", {}).get("allPlays", [])
    sample = plays[0] if plays else {}
    summary = {
        "game_pk": game["gamePk"],
        "game_status": payload.get("gameData", {}).get("status", {}).get("detailedState"),
        "play_count": len(plays),
        "sample_keys": sorted(sample.keys()),
        "sample_about": sample.get("about", {}),
        "sample_count": sample.get("count", {}),
        "sample_result": sample.get("result", {}),
        "sample_matchup": sample.get("matchup", {}),
        "final_linescore": payload.get("liveData", {}).get("linescore", {}).get("teams", {}),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
