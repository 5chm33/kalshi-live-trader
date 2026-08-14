"""Build the V11 non-executable MLB score-state/quote study dataset."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mlb_quote_study import build_quote_study


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 MLB/Kalshi retrospective quote alignment")
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--max-quote-delay-seconds", type=int, default=120)
    args = parser.parse_args()
    print(json.dumps(build_quote_study(args.database, args.max_quote_delay_seconds), sort_keys=True))


if __name__ == "__main__":
    main()
