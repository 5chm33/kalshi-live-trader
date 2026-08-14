"""Run the V11 out-of-sample empirical MLB model versus archived Kalshi quotes study."""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mlb_model_quote_study import evaluate_model_vs_quotes


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 out-of-sample MLB model/quote study")
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--training-end", required=True)
    parser.add_argument("--test-start", required=True)
    parser.add_argument("--test-end", required=True)
    parser.add_argument("--minimum-games", type=int, default=100)
    parser.add_argument("--minimum-expected-net", type=Decimal, default=Decimal("0.02"))
    args = parser.parse_args()
    report = evaluate_model_vs_quotes(
        args.database, args.training_end, args.test_start, args.test_end,
        args.minimum_games, args.minimum_expected_net,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
