"""Run one read-only Kalshi settlement reconciliation cycle."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.run_mlb_paper import load_config
from research.settle import SettlementReconciler
from research.store import ResearchStore


def run_once(config_file: Path) -> dict[str, int]:
    api_config, config = load_config(config_file)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    store = ResearchStore(config.database_path)
    return SettlementReconciler(client, store).run()


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper settlement reconciliation")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    args = parser.parse_args()
    print(json.dumps(run_once(args.config), sort_keys=True))


if __name__ == "__main__":
    main()
