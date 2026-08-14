"""Inspect open mutually exclusive events via signed GET requests only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.guards import is_political_market
from research.kalshi_readonly import ReadOnlyKalshiClient
from research.run_mlb_paper import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    api_config, config = load_config(args.config)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    page = client.get("/events", {"status": "open", "limit": args.limit})
    events = [event for event in page.get("events", []) if isinstance(event, dict)]
    eligible = [event for event in events if bool(event.get("mutually_exclusive")) and not is_political_market(event)]
    detail = client.get(f"/events/{eligible[0]['event_ticker']}") if eligible else {}
    print(json.dumps({
        "events_returned": len(events), "eligible_mutually_exclusive": len(eligible),
        "sample_event": eligible[0] if eligible else None,
        "sample_detail_keys": sorted(detail.keys()),
        "sample_detail": detail,
    }, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
