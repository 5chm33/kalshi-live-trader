"""Archived Kalshi MLB market/candlestick collector for V11 research.

Candlesticks are recorded as quote-history telemetry, not assumed fills or
order-book depth. The collector only uses the GET-only Kalshi client.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.store import ResearchStore


class KalshiHistoricalMLBCollector:
    def __init__(self, client: ReadOnlyKalshiClient, store: ResearchStore):
        self.client = client
        self.store = store

    @staticmethod
    def _time(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc)
        except ValueError:
            return None

    def collect_markets(self, max_pages: int = 1, max_markets: int = 100) -> dict[str, int]:
        cursor: str | None = None
        found = stored = candles = skipped = 0
        for _ in range(max_pages):
            page = self.client.historical_markets("KXMLBGAME", limit=min(1000, max_markets - found), cursor=cursor)
            markets = [item for item in page.get("markets", []) if isinstance(item, Mapping)]
            for market in markets:
                found += 1
                now = datetime.now(timezone.utc)
                self.store.record_historical_market(market, now)
                stored += 1
                close_time = self._time(market.get("close_time"))
                if close_time is None:
                    skipped += 1
                    continue
                # A 13-hour lifecycle window is well inside the 10k 1-minute
                # limit and contains typical same-day game action through close.
                start = int((close_time - timedelta(hours=12)).timestamp())
                end = int((close_time + timedelta(hours=1)).timestamp())
                payload = self.client.historical_candlesticks(str(market["ticker"]), start, end, 1)
                market_candles = [item for item in payload.get("candlesticks", []) if isinstance(item, Mapping)]
                self.store.record_historical_candles(str(market["ticker"]), market_candles, now)
                candles += len(market_candles)
                if found >= max_markets:
                    break
            if found >= max_markets:
                break
            cursor = page.get("cursor") or None
            if not cursor or not markets:
                break
        return {"markets_found": found, "markets_stored": stored, "candles_stored": candles, "markets_skipped": skipped}
