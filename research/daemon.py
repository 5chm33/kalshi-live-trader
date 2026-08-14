"""Continuous V11 paper-only data collector.

This process only invokes `run_once`, which uses a GET-only Kalshi client and a
paper broker. It cannot submit or manage a production order.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.run_mlb_paper import run_once
from research.run_settlement_reconcile import run_once as reconcile_settlements


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper-only research collector")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--interval-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if args.interval_seconds < 15:
        raise ValueError("interval must be at least 15 seconds")

    while True:
        started = time.monotonic()
        try:
            settlement_summary = reconcile_settlements(args.config)
            summary = run_once(args.config)
            summary["settlement_reconciliation"] = settlement_summary
            logging.info("PAPER-ONLY cycle=%s", json.dumps(summary, sort_keys=True))
        except KeyboardInterrupt:
            raise
        except Exception:
            logging.exception("PAPER-ONLY cycle failed; no exchange mutation was attempted")
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, args.interval_seconds - elapsed))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
