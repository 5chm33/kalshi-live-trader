"""Verify a V11 SQLite backup can be opened and has consistent core tables."""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

CORE_TABLES = ("observations", "signals", "paper_orders", "paper_fills", "strategy_manifests", "decision_records", "evaluation_snapshots")


def verify(backup: Path) -> dict[str, object]:
    if not backup.exists():
        raise FileNotFoundError(backup)
    connection = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity check failed: {integrity}")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [name for name in CORE_TABLES if name not in tables]
        if missing:
            raise RuntimeError(f"backup missing core tables: {missing}")
        counts = {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in CORE_TABLES}
    finally:
        connection.close()
    return {"backup": str(backup), "integrity_check": "ok", "counts": counts, "restore_readable": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.backup), sort_keys=True))


if __name__ == "__main__":
    main()
