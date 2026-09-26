"""Cross-check a new Kalshi WebSocket snapshot against a separately fetched REST book.

A freshly subscribed snapshot with a monotonically identified sequence cannot be
replayed from an HTTP cache. Kalshi does not publish a venue timestamp on its
snapshot, so this is a bounded live-channel confirmation, NOT a guarantee the
book will be unchanged by the time an IOC reaches the matching engine.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from decimal import Decimal

from core.kalshi_client import KalshiClient
from core.public_market import BookQuote, MarketDataError, quote_from_orderbook

WS_URL = 'wss://external-api-ws.kalshi.com/trade-api/ws/v2'


@dataclass(frozen=True)
class ConfirmedBook:
    quote: BookQuote
    sequence: int
    received_monotonic: float


def parse_snapshot(message: dict, ticker: str) -> ConfirmedBook:
    if (not isinstance(message, dict) or message.get('type') != 'orderbook_snapshot'
            or isinstance(message.get('seq'), bool) or not isinstance(message.get('seq'), int)
            or message['seq'] < 0 or not isinstance(message.get('msg'), dict)
            or message['msg'].get('market_ticker') != ticker):
        raise MarketDataError('Missing or mismatched venue-sequenced snapshot')
    body = message['msg']
    book = {'yes_dollars': body.get('yes_dollars_fp'), 'no_dollars': body.get('no_dollars_fp')}
    quote = quote_from_orderbook(book)
    if quote is None:
        raise MarketDataError('Venue WebSocket book is one-sided or empty')
    return ConfirmedBook(quote, message['seq'], time.monotonic())


async def _subscribe_once(client: KalshiClient, ticker: str) -> ConfirmedBook:
    # Exact Kalshi WebSocket GET path (not the /trade-api/v2 REST path).
    headers = client._auth_headers('GET', '/trade-api/ws/v2')
    from websockets.asyncio.client import connect
    async with asyncio.timeout(6):
        async with connect(WS_URL, additional_headers=headers, open_timeout=4,
                           max_size=1_000_000, ping_interval=15) as ws:
            await ws.send(json.dumps({'id': 1, 'cmd': 'subscribe',
                                      'params': {'channels': ['orderbook_delta'],
                                                 'market_ticker': ticker}}))
            for _ in range(5):
                msg = json.loads(await ws.recv())
                if msg.get('type') == 'error':
                    raise MarketDataError('Venue WebSocket subscription rejected')
                if msg.get('type') == 'orderbook_snapshot':
                    return parse_snapshot(msg, ticker)
    raise MarketDataError('No fresh venue orderbook snapshot received')


def fresh_confirmed_quote(client: KalshiClient, public, ticker: str) -> BookQuote:
    """Reject stale-cache REST mismatches, slow handshakes, and invalid snapshots."""
    start = time.monotonic()
    try:
        seen = asyncio.run(_subscribe_once(client, ticker))
    except Exception as exc:
        raise MarketDataError(f'Venue WebSocket freshness check failed: {type(exc).__name__}') from None
    if time.monotonic() - seen.received_monotonic > 1:
        raise MarketDataError('Venue WebSocket snapshot aged out')
    response = public.get_orderbook(ticker, depth=1)
    rest = quote_from_orderbook(response)
    if rest is None or time.monotonic() - start > 5:
        raise MarketDataError('Fresh independent REST orderbook unavailable')
    a, b = seen.quote, rest
    if any(getattr(a, name) != getattr(b, name)
           for name in ('yes_bid', 'yes_ask', 'no_bid', 'no_ask',
                        'yes_ask_size', 'no_ask_size')):
        raise MarketDataError('REST and newly generated venue WebSocket snapshot disagree')
    return a
