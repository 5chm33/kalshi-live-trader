"""Read-only weather ensemble diagnostic for V11 research."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.weather import OpenMeteoEnsembleFeed

CITIES = {
    "dallas": (32.78, -96.80, "America/Chicago"),
    "new_york": (40.71, -74.01, "America/New_York"),
    "seattle": (47.61, -122.33, "America/Los_Angeles"),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper-only ensemble diagnostic")
    parser.add_argument("--city", choices=sorted(CITIES), default="dallas")
    parser.add_argument("--date", default=(datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat())
    parser.add_argument("--kind", choices=("high", "low"), default="high")
    args = parser.parse_args()

    latitude, longitude, timezone_name = CITIES[args.city]
    snapshot = OpenMeteoEnsembleFeed().daily_temperature(
        args.city, latitude, longitude, timezone_name, args.date, args.kind
    )
    report = {
        "mode": "read_only_no_signal",
        "city": snapshot.city,
        "target_date": snapshot.target_date,
        "variable": snapshot.variable,
        "actual_member_count": snapshot.member_count,
        "members_by_model": {model: len(values) for model, values in snapshot.members_by_model.items()},
        "payload_sha256": snapshot.stamp.payload_sha256,
    }
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
