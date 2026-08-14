"""Read-only authenticated Kalshi WebSocket market-data client.

The stream authenticates only to receive public market data. It does not expose
any REST order method and has no path to submit an order.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from collections.abc import AsyncIterator
from typing import Any, Iterable, Mapping

import websockets
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.stream_health import StreamHealth

WS_PRODUCTION = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"
WS_DEMO = "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"


class KalshiMarketStream:
    """Authenticated market-data stream with reconnect/backoff behavior."""

    def __init__(self, readonly_client: ReadOnlyKalshiClient, environment: str = "production"):
        if environment not in {"production", "demo"}:
            raise ValueError("environment must be 'production' or 'demo'")
        self.client = readonly_client
        self.ws_url = WS_PRODUCTION if environment == "production" else WS_DEMO
        self._request_id = 0
        self.health = StreamHealth()

    def _headers(self) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        path = "/trade-api/ws/v2"
        message = (timestamp + "GET" + path).encode("utf-8")
        signature = self.client.private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.client.api_key,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("ascii"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }

    def _subscription(self, channels: Iterable[str], tickers: Iterable[str] | None) -> dict[str, Any]:
        self._request_id += 1
        params: dict[str, Any] = {"channels": list(channels)}
        ticker_list = list(tickers or [])
        if ticker_list:
            params["market_tickers"] = ticker_list
        return {"id": self._request_id, "cmd": "subscribe", "params": params}

    async def events(
        self,
        channels: Iterable[str],
        tickers: Iterable[str] | None = None,
        reconnect_max_seconds: float = 30.0,
    ) -> AsyncIterator[Mapping[str, Any]]:
        """Yield raw market-data messages, reconnecting after transient failures."""
        delay = 0.5
        while True:
            try:
                async with websockets.connect(
                    self.ws_url,
                    additional_headers=self._headers(),
                    ping_interval=20,
                    ping_timeout=20,
                    max_queue=5000,
                ) as websocket:
                    self.health.connected()
                    await websocket.send(json.dumps(self._subscription(channels, tickers)))
                    delay = 0.5
                    async for message in websocket:
                        payload = json.loads(message)
                        if not isinstance(payload, Mapping):
                            continue
                        if payload.get("type") == "error":
                            raise RuntimeError(f"Kalshi WebSocket error: {payload.get('msg')}")
                        yield payload
            except asyncio.CancelledError:
                raise
            except Exception:
                self.health.errored()
                await asyncio.sleep(delay)
                delay = min(delay * 2, reconnect_max_seconds)
