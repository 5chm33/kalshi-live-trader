"""Independent local V11 health check; returns nonzero on failed collector or stale ledger conditions."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SERVICES = ("kalshi-research-v11.service", "kalshi-research-v11-ws.service", "kalshi-research-v11-parity.service", "kalshi-research-v11-weather.service")


def _active(service: str) -> bool:
    return subprocess.run(["systemctl", "is-active", "--quiet", service], check=False).returncode == 0


def health(database: Path, max_observation_age_seconds: int) -> dict[str, object]:
    status = {service: _active(service) for service in SERVICES}
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        row = connection.execute("SELECT MAX(received_at) FROM observations").fetchone()
    finally:
        connection.close()
    latest = row[0]
    age = None
    if latest:
        observed_at = datetime.fromisoformat(latest)
        age = (datetime.now(timezone.utc) - observed_at).total_seconds()
    healthy = all(status.values()) and integrity == "ok" and (age is not None and age <= max_observation_age_seconds)
    return {"healthy": healthy, "mode": "paper_only_no_orders", "services": status, "integrity_check": integrity,
            "latest_observation_at": latest, "latest_observation_age_seconds": age,
            "max_observation_age_seconds": max_observation_age_seconds,
            "alert_delivery": "not_configured; nonzero exit is intended for systemd/journal or an external monitor"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--max-observation-age-seconds", type=int, default=7200)
    args = parser.parse_args()
    result = health(args.database, args.max_observation_age_seconds)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["healthy"] else 1)


if __name__ == "__main__":
    main()
