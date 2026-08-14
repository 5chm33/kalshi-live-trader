"""Append a signed retired-hypothesis record to the local paper ledger."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.audit import AuditSigner
from research.negative_results import NegativeResult
from research.store import ResearchStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--signing-key", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.record.read_text(encoding="utf-8"))
    result = NegativeResult(**payload)
    signer = AuditSigner.from_file(args.signing_key, required=True)
    store = ResearchStore(args.database)
    store.record_negative_result(result, signer.sign(result.result_sha256))
    print(json.dumps({"result_sha256": result.result_sha256, "strategy": result.strategy_family,
                      "version": result.strategy_version, "signed": signer.enabled}, sort_keys=True))


if __name__ == "__main__":
    main()
