"""Public read-only diagnostic for Kalshi crypto-series metadata and current contracts."""
from __future__ import annotations

import json
from urllib.parse import urlencode

import requests

BASE = "https://external-api.kalshi.com/trade-api/v2"


def fetch(path: str, **params):
    response = requests.get(f"{BASE}{path}", params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def main() -> None:
    report = {}
    for ticker in ("KXBTC15M", "KXBTCD", "KXETH15M"):
        try:
            series = fetch(f"/series/{ticker}").get("series", {})
            markets = fetch("/markets", series_ticker=ticker, status="open", limit=200).get("markets", [])
            report[ticker] = {"series": series, "open_markets": markets[:10], "open_count": len(markets)}
        except requests.HTTPError as exc:
            report[ticker] = {"error": str(exc)}
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
