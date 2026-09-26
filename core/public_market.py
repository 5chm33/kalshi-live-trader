"""Read-only Kalshi market-data access. This module has no order endpoints."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

import requests

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"


class MarketDataError(RuntimeError):
    """Do not trade or score a market if its data is missing or malformed."""


def decimal_price(value: object) -> Decimal:
    try:
        price = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MarketDataError(f"Invalid price: {value!r}") from exc
    if not price.is_finite() or not Decimal("0") < price < Decimal("1"):
        raise MarketDataError(f"Price outside (0, 1): {value!r}")
    return price


@dataclass(frozen=True)
class BookQuote:
    yes_bid: Decimal
    yes_ask: Decimal
    no_bid: Decimal
    no_ask: Decimal
    yes_ask_size: Decimal
    no_ask_size: Decimal


def quote_from_orderbook(book: dict) -> Optional[BookQuote]:
    """Use the opposite outcome's best BID to compute each executable ask.

    None means the book is one-sided or has no real positive size. Never invent
    a quote from a last trade, 0, an absent field, or an old discovery snapshot.
    """
    if not isinstance(book, dict):
        raise MarketDataError("Orderbook is not an object")

    def best(key: str) -> tuple[Decimal, Decimal] | None:
        levels = book.get(key)
        if not isinstance(levels, list):
            raise MarketDataError(f"Orderbook missing {key}")
        parsed = []
        for level in levels:
            if not isinstance(level, list) or len(level) < 2:
                raise MarketDataError(f"Malformed {key} level")
            price = decimal_price(level[0])
            try:
                size = Decimal(str(level[1]))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise MarketDataError("Malformed orderbook size") from exc
            if not size.is_finite() or size < 0:
                raise MarketDataError("Invalid orderbook size")
            if size > 0:
                parsed.append((price, size))
        return max(parsed, key=lambda item: item[0]) if parsed else None

    yes, no = best("yes_dollars"), best("no_dollars")
    if yes is None or no is None:
        return None
    yes_bid, yes_bid_size = yes
    no_bid, no_bid_size = no
    yes_ask = Decimal("1") - no_bid
    no_ask = Decimal("1") - yes_bid
    if yes_bid > yes_ask or no_bid > no_ask:
        raise MarketDataError("Crossed/inconsistent orderbook")
    return BookQuote(yes_bid, yes_ask, no_bid, no_ask, no_bid_size, yes_bid_size)


class PublicMarketClient:
    """Bounded read-only requests. Any HTTP or schema error fails closed."""

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict | None = None) -> dict:
        response = self.session.get(BASE_URL + path, params=params, timeout=12,
                                    allow_redirects=False)
        response.raise_for_status()
        if 300 <= response.status_code < 400:
            raise MarketDataError('Unexpected Kalshi API redirect')
        payload = response.json()
        if not isinstance(payload, dict):
            raise MarketDataError("Non-object Kalshi response")
        return payload

    def get_markets(self, series_ticker: str, status: str = "open", limit: int = 200) -> list[dict]:
        markets = []
        cursor = None
        seen = set()
        for _ in range(10):
            params = {"series_ticker": series_ticker, "status": status, "limit": min(limit, 1000)}
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/markets", params)
            page = payload.get("markets")
            if not isinstance(page, list):
                raise MarketDataError("Missing markets array")
            markets.extend(page)
            cursor = payload.get("cursor")
            if not cursor:
                return markets
            if cursor in seen:
                raise MarketDataError("Market pagination cursor loop")
            seen.add(cursor)
        raise MarketDataError("Market pagination exceeded 10 pages; data incomplete")

    def get_orderbook(self, ticker: str, *, depth: int | None = None) -> dict:
        if depth is not None and (isinstance(depth, bool) or not isinstance(depth, int)
                                  or not 1 <= depth <= 100):
            raise MarketDataError("Orderbook depth must be 1–100")
        payload = self._get(f"/markets/{ticker}/orderbook",
                            {"depth": depth} if depth is not None else None)
        book = payload.get("orderbook_fp")
        if not isinstance(book, dict):
            raise MarketDataError("Missing orderbook_fp")
        return book

    def get_series(self, ticker: str) -> dict:
        if not ticker or not ticker.isalnum():
            raise MarketDataError("Invalid series ticker")
        data = self._get(f"/series/{ticker}").get("series")
        if not isinstance(data, dict) or data.get("ticker") != ticker:
            raise MarketDataError("Missing or mismatched series metadata")
        return data

    def get_event(self, ticker: str) -> dict:
        if not ticker or not all(c.isalnum() or c == '-' for c in ticker):
            raise MarketDataError("Invalid event ticker")
        data = self._get(f"/events/{ticker}", {"with_nested_markets": "true"}).get("event")
        if not isinstance(data, dict) or data.get("event_ticker") != ticker or not isinstance(data.get("markets"), list):
            raise MarketDataError("Missing or mismatched event metadata")
        return data
