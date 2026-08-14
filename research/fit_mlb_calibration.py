"""Fit a bounded, empirical MLB late-lead calibration report from the local ledger."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.mlb_calibration import EmpiricalMLBModel


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit V11 empirical MLB calibration model")
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--training-end", required=True, help="ISO date cutoff, e.g. 2025-09-30")
    parser.add_argument("--minimum-games", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("data/mlb_empirical_late_lead_v1.json"))
    args = parser.parse_args()
    model = EmpiricalMLBModel.fit(args.database, args.training_end, args.minimum_games)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    model.save(args.output)
    print(args.output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
