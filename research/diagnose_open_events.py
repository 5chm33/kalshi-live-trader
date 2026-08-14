"""Inspect current open-event metadata using signed GET only; no exchange mutation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.run_mlb_paper import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    api_config, config = load_config(args.config)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    payload = client.get("/events", {"status": "open", "limit": args.limit})
    events = payload.get("events", [])
    sample = events[0] if events else {}
    print(json.dumps({
        "response_keys": sorted(payload.keys()), "event_count": len(events),
        "sample_keys": sorted(sample.keys()) if isinstance(sample, dict) else [],
        "sample": sample,
    }, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
