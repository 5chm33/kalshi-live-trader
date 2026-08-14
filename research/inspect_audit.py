"""Read-only inspection of immutable V11 manifest and decision-record payloads."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.store import ResearchStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    args = parser.parse_args()
    store = ResearchStore(args.database)
    with store.connect() as conn:
        manifests = [dict(row) for row in conn.execute("SELECT manifest_id, payload_json FROM strategy_manifests ORDER BY created_at")]
        decisions = [dict(row) for row in conn.execute("SELECT record_sha256, manifest_id, payload_json FROM decision_records ORDER BY created_at")]
    print(json.dumps({"manifests": manifests, "decisions": decisions}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
