"""Non-mutating summary of prospective structural-parity research observations."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.store import ResearchStore


def _assessments(entity_type: str, payload: dict) -> list[dict]:
    if entity_type == "binary_complement_parity":
        return [payload.get("assessment", {})]
    return list(payload.get("assessments", []))


def report(database: Path) -> dict:
    store = ResearchStore(database)
    totals = defaultdict(lambda: {"observations": 0, "assessments": 0, "candidates": 0, "best_net": None, "candidate_net_total": Decimal("0")})
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT entity_type, payload_json FROM observations WHERE entity_type IN ('binary_complement_parity','directional_threshold_cover','mec_no_basket')"
        ).fetchall()
    for row in rows:
        entity_type = str(row["entity_type"])
        payload = json.loads(row["payload_json"])
        bucket = totals[entity_type]
        bucket["observations"] += 1
        for assessment in _assessments(entity_type, payload):
            if not isinstance(assessment, dict):
                continue
            bucket["assessments"] += 1
            net = Decimal(str(assessment.get("net_locked_value", "0")))
            best = bucket["best_net"]
            bucket["best_net"] = net if best is None or net > best else best
            if assessment.get("status") == "candidate":
                bucket["candidates"] += 1
                bucket["candidate_net_total"] += net
    formatted = {}
    for name, value in totals.items():
        formatted[name] = {
            "observations": value["observations"], "assessments": value["assessments"], "candidates": value["candidates"],
            "best_net_locked_value": str(value["best_net"]) if value["best_net"] is not None else None,
            "candidate_net_total": str(value["candidate_net_total"]),
        }
    return {"mode": "paper_only_no_orders", "studies": formatted}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    args = parser.parse_args()
    print(json.dumps(report(args.database), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
