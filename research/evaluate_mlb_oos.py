"""Print an out-of-sample empirical MLB probability-quality report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mlb_oos import evaluate_out_of_sample


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 out-of-sample MLB calibration evaluation")
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--training-end", required=True)
    parser.add_argument("--test-start", required=True)
    parser.add_argument("--test-end", required=True)
    parser.add_argument("--minimum-games", type=int, default=100)
    args = parser.parse_args()
    report = evaluate_out_of_sample(
        args.database, args.training_end, args.test_start, args.test_end, args.minimum_games
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
