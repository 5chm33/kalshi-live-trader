"""Create a signed, append-only V11 evaluation snapshot from pre-existing JSON inputs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.audit import AuditSigner, DecisionRecord, StrategyManifest, git_commit, sha256
from research.store import ResearchStore


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object in {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("decision", type=Path)
    parser.add_argument("result", type=Path)
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--signing-key", type=Path, required=True, help="local-only 0600 audit key")
    args = parser.parse_args()
    manifest_payload = _load(args.manifest)
    manifest_payload.setdefault("code_commit", git_commit(ROOT))
    manifest = StrategyManifest(**manifest_payload)
    decision_payload = _load(args.decision)
    decision_payload["manifest_id"] = manifest.manifest_id
    decision = DecisionRecord(**decision_payload)
    result = _load(args.result)
    if result.get("dataset_sha256") != decision.dataset_sha256:
        raise ValueError("result dataset_sha256 must match decision record")
    signer = AuditSigner.from_file(args.signing_key, required=True)
    store = ResearchStore(args.database)
    store.record_manifest(manifest)
    store.record_decision_record(decision, signer.sign(decision.record_sha256))
    snapshot_payload = {"manifest": manifest.manifest_id, "decision": decision.record_sha256, "dataset": decision.dataset_sha256, "commit": git_commit(ROOT), "result": result}
    snapshot_sha256 = sha256(snapshot_payload)
    store.record_evaluation_snapshot(snapshot_sha256, manifest.manifest_id, decision.record_sha256, decision.dataset_sha256, git_commit(ROOT), result, signer.sign(snapshot_sha256))
    print(json.dumps({"manifest_id": manifest.manifest_id, "decision_record": decision.record_sha256, "snapshot": snapshot_sha256, "signed": signer.enabled}, sort_keys=True))


if __name__ == "__main__":
    main()
