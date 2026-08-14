"""Authenticated, GET-only Kalshi client for V11 research.

This module intentionally exposes no POST, PUT, PATCH, or DELETE method. It is
therefore incapable of placing, canceling, amending, or exiting an order.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

PRODUCTION_BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
DEMO_BASE_URL = "https://external-api.demo.kalshi.co/trade-api/v2"


class ReadOnlyKalshiClient:
    """Kalshi API client restricted to signed GET requests."""

    def __init__(self, config: Mapping[str, Any], environment: str = "production"):
        if environment not in {"production", "demo"}:
            raise ValueError("environment must be 'production' or 'demo'")
        self.base_url = PRODUCTION_BASE_URL if environment == "production" else DEMO_BASE_URL
        self.api_key = str(config.get("api_key", ""))
        if not self.api_key:
            raise ValueError("missing api_key")
        self.private_key = self._load_key(config)
        self.session = requests.Session()
        self._last_request = 0.0
        self._min_interval = 0.05  # Conservative 20 requests/sec max.

    @staticmethod
    def _load_key(config: Mapping[str, Any]):
        raw = None
        for key in ("private_key_string", "private_key", "private_key_path"):
            value = config.get(key)
            if not value:
                continue
            string = str(value)
            if string.startswith("-----BEGIN"):
                raw = string.replace("\\n", "\n").encode("utf-8")
            else:
                path = Path(string)
                if path.exists():
                    raw = path.read_bytes()
            if raw:
                break
        if raw is None:
            raise ValueError("no readable RSA private key in configuration")
        return serialization.load_pem_private_key(raw, password=None, backend=default_backend())

    def _headers(self, path_with_query: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        signed_path = path_with_query.split("?", 1)[0]
        message = (timestamp + "GET" + signed_path).encode("utf-8")
        signature = self.private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "Accept": "application/json",
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("ascii"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }

    def get(self, path: str, params: Mapping[str, Any] | None = None, timeout: int = 15) -> dict[str, Any]:
        """Perform a signed GET only; all non-GET exchange mutation is impossible here."""
        if not path.startswith("/"):
            raise ValueError("path must start with '/'")
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
        path_with_query = f"{path}?{query}" if query else path
        wait = self._min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.session.get(
            self.base_url + path_with_query,
            headers=self._headers(path_with_query),
            timeout=timeout,
        )
        self._last_request = time.monotonic()
        response.raise_for_status()
        return response.json()

    def balance(self) -> dict[str, Any]:
        return self.get("/portfolio/balance")

    def positions(self, cursor: str | None = None) -> dict[str, Any]:
        return self.get("/portfolio/positions", {"count_filter": "position", "cursor": cursor})

    def fills(self, cursor: str | None = None, limit: int = 1000) -> dict[str, Any]:
        return self.get("/portfolio/fills", {"cursor": cursor, "limit": limit})

    def resting_orders(self, cursor: str | None = None, limit: int = 1000) -> dict[str, Any]:
        return self.get("/portfolio/orders", {"status": "resting", "cursor": cursor, "limit": limit})

    def open_markets(self, limit: int = 1000, cursor: str | None = None) -> dict[str, Any]:
        """Discover open markets through a signed GET request only."""
        return self.get("/markets", {"status": "open", "limit": limit, "cursor": cursor})

    def markets(self, series_ticker: str, limit: int = 1000, cursor: str | None = None) -> dict[str, Any]:
        return self.get("/markets", {"status": "open", "series_ticker": series_ticker, "limit": limit, "cursor": cursor})

    def market(self, ticker: str) -> dict[str, Any]:
        return self.get(f"/markets/{ticker}")

    def orderbook(self, ticker: str) -> dict[str, Any]:
        return self.get(f"/markets/{ticker}/orderbook")

    def historical_markets(
        self, series_ticker: str, limit: int = 1000, cursor: str | None = None
    ) -> dict[str, Any]:
        return self.get(
            "/historical/markets",
            {"series_ticker": series_ticker, "limit": limit, "cursor": cursor},
        )

    def historical_candlesticks(
        self, ticker: str, start_ts: int, end_ts: int, period_interval: int = 1
    ) -> dict[str, Any]:
        if period_interval not in {1, 60, 1440}:
            raise ValueError("period_interval must be one of 1, 60, 1440")
        return self.get(
            f"/historical/markets/{ticker}/candlesticks",
            {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval},
        )
