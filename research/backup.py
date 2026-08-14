"""Safe local backups for the paper-research SQLite ledger; no network or exchange capability."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def create_backup(database: Path, backup_dir: Path, retain: int = 14) -> dict[str, object]:
    if not database.exists():
        raise FileNotFoundError(database)
    if retain < 1:
        raise ValueError("retain must be at least one")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"research_v11_{stamp}.sqlite3"
    temporary = target.with_suffix(".sqlite3.tmp")
    source = sqlite3.connect(database)
    destination = sqlite3.connect(temporary)
    try:
        source.execute("PRAGMA wal_checkpoint(FULL)")
        source.backup(destination)
        destination.commit()
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"backup integrity check failed: {integrity}")
    finally:
        destination.close()
        source.close()
    os.replace(temporary, target)
    checksum = _sha256(target)
    manifest = target.with_suffix(".json")
    manifest.write_text(json.dumps({"created_at": stamp, "database": str(database), "backup": target.name, "sha256": checksum, "integrity_check": "ok"}, sort_keys=True) + "\n", encoding="utf-8")
    backups = sorted(backup_dir.glob("research_v11_*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True)
    removed: list[str] = []
    for stale in backups[retain:]:
        stale.unlink(missing_ok=True)
        stale.with_suffix(".json").unlink(missing_ok=True)
        removed.append(stale.name)
    return {"backup": str(target), "sha256": checksum, "retained": min(len(backups), retain), "removed": removed, "integrity_check": "ok"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--backup-dir", type=Path, default=Path("backups"))
    parser.add_argument("--retain", type=int, default=14)
    args = parser.parse_args()
    print(json.dumps(create_backup(args.database, args.backup_dir, args.retain), sort_keys=True))


if __name__ == "__main__":
    main()
