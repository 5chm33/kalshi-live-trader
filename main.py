"""Retired live-trading entry point.

V10 never demonstrated fee-adjusted profitability and had material state and
execution defects. It is intentionally disabled. The active V11 system is
paper-only and uses `research/daemon.py` or `research/run_mlb_paper.py`.
"""
from __future__ import annotations

import sys

MESSAGE = """
KALSHI LIVE EXECUTION IS DISABLED.

This repository is under V11 paper-only research. No evidence-based readiness
review has authorized a production order path. Run one of:

  python3 research/run_mlb_paper.py --config config.json
  python3 research/daemon.py --config config.json --interval-seconds 60
  python3 research/run_evaluation.py --database data/research_v11.sqlite3

The paper collector uses authenticated GET requests only and cannot submit,
amend, cancel, or exit a Kalshi order.
""".strip()


def main() -> int:
    print(MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
