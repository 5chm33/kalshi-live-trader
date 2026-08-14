"""Run the V11 exploratory-only MLB/Kalshi quote-bucket report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.explore_mlb_quote_buckets import explore


def main() -> None:
    parser = argparse.ArgumentParser(description="Exploratory V11 MLB quote bucket report")
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--minimum-rows", type=int, default=25)
    args = parser.parse_args()
    print(json.dumps(explore(args.database, args.minimum_rows), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
