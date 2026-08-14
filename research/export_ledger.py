"""Create an auditable compressed JSON export of the local paper-research ledger."""
from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

EXPORT_TABLES = ("observations", "signals", "paper_orders", "paper_fills", "paper_marks", "settlements", "strategy_manifests", "decision_records", "evaluation_snapshots")


def export(database: Path, output_dir: Path, retain: int = 30) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"research_v11_{stamp}.ndjson.gz"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    try:
        with gzip.open(path, "wt", encoding="utf-8") as out:
            for table in EXPORT_TABLES:
                try:
                    rows = connection.execute(f"SELECT * FROM {table}")
                except sqlite3.OperationalError:
                    continue
                count = 0
                for row in rows:
                    out.write(json.dumps({"table": table, "row": dict(row)}, sort_keys=True, default=str) + "\n")
                    count += 1
                counts[table] = count
    finally:
        connection.close()
    exports = sorted(output_dir.glob("research_v11_*.ndjson.gz"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in exports[retain:]:
        stale.unlink(missing_ok=True)
    return {"export": str(path), "counts": counts, "retained": min(len(exports), retain)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--output-dir", type=Path, default=Path("exports"))
    parser.add_argument("--retain", type=int, default=30)
    args = parser.parse_args()
    print(json.dumps(export(args.database, args.output_dir, args.retain), sort_keys=True))


if __name__ == "__main__":
    main()
