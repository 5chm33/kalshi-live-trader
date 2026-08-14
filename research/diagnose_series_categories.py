"""Public, read-only Kalshi series discovery; no account access or mutation."""
from __future__ import annotations

import json
from collections import Counter

import requests

BASE = "https://external-api.kalshi.com/trade-api/v2"


def main() -> None:
    response = requests.get(f"{BASE}/series", params={"include_volume": "true"}, timeout=20)
    response.raise_for_status()
    series = [row for row in response.json().get("series", []) if isinstance(row, dict)]
    categories = Counter(str(row.get("category", "unknown")) for row in series)
    top = sorted(series, key=lambda row: float(row.get("volume_fp", "0") or 0), reverse=True)[:75]
    print(json.dumps({
        "series_returned": len(series), "categories": dict(sorted(categories.items())),
        "top_series": [{key: row.get(key) for key in ("ticker", "title", "category", "frequency", "fee_type", "fee_multiplier", "volume_fp", "settlement_sources", "additional_prohibitions")} for row in top],
    }, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
