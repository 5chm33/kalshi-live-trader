"""Public read-only inspection of candidate weather-series settlement metadata."""
from __future__ import annotations

import json

import requests

BASE = "https://external-api.kalshi.com/trade-api/v2"
SERIES = ("KXHIGHNY", "KXLOWNY", "KXHIGHTCHI", "KXLOWTCHI", "KXHIGHTDC", "KXLOWTDC")


def main() -> None:
    report = {}
    for ticker in SERIES:
        response = requests.get(f"{BASE}/series/{ticker}", timeout=20)
        if response.status_code == 404:
            report[ticker] = {"status": "not_found"}
            continue
        response.raise_for_status()
        data = response.json().get("series", {})
        report[ticker] = {key: data.get(key) for key in (
            "ticker", "title", "category", "frequency", "settlement_sources", "contract_url", "contract_terms_url", "fee_type", "fee_multiplier", "additional_prohibitions",
        )}
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
