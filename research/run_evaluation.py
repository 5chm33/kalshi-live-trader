"""Print an evidence-only report from the local V11 paper ledger."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.evaluate import evaluate


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate V11 paper-research ledger")
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    args = parser.parse_args()
    print(json.dumps(evaluate(args.database), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
