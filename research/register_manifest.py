"""Register an immutable pre-analysis manifest in a V11 paper ledger."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.audit import StrategyManifest
from research.store import ResearchStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, help="JSON document matching StrategyManifest fields")
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest = StrategyManifest(**payload)
    ResearchStore(args.database).record_manifest(manifest)
    print(json.dumps({"manifest_id": manifest.manifest_id, "strategy": manifest.strategy_family, "version": manifest.strategy_version}, sort_keys=True))


if __name__ == "__main__":
    main()
