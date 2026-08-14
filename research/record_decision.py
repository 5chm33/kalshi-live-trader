"""Record a signed, append-only pre-analysis decision record for an existing manifest."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.audit import AuditSigner, DecisionRecord, StrategyManifest
from research.store import ResearchStore


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object at {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("decision", type=Path)
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--signing-key", type=Path, required=True)
    args = parser.parse_args()
    manifest_payload = _load(args.manifest)
    manifest = StrategyManifest(**manifest_payload)
    decision_payload = _load(args.decision)
    decision_payload["manifest_id"] = manifest.manifest_id
    decision = DecisionRecord(**decision_payload)
    signer = AuditSigner.from_file(args.signing_key, required=True)
    store = ResearchStore(args.database)
    store.record_manifest(manifest)
    store.record_decision_record(decision, signer.sign(decision.record_sha256))
    print(json.dumps({"manifest_id": manifest.manifest_id, "record_sha256": decision.record_sha256, "signed": signer.enabled}, sort_keys=True))


if __name__ == "__main__":
    main()
