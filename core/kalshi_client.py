"""
Kalshi API Client — v10
========================
Clean synchronous REST client + async WebSocket client.
Supports both legacy V1 and new V2 order endpoints.
Uses IOC (immediate-or-cancel) for sniping stale prices.
"""

import os
import time
import random
import base64
import json
import logging
import threading
import requests
from typing import Dict, List, Optional, Callable

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

log = logging.getLogger('KALSHI')

BASE_URL = "https://api.elections.kalshi.com"
WS_URL = "wss://api.elections.kalshi.com/trade-api/ws/v2"


class KalshiClient:
    """Synchronous Kalshi REST API client with rate limiting."""

    def __init__(self, config: dict):
        self.api_key = config.get('api_key', '')
        self.base_url = BASE_URL
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.private_key = None
        self._last_req = 0.0
        self._min_interval = 0.05  # 20 req/sec (well under 30/sec limit)

        # Load RSA key
        pem = None
        for key in ('private_key_string', 'private_key', 'private_key_path'):
            val = config.get(key)
            if not val:
                continue
            if val.startswith('-----BEGIN'):
                pem = val.replace('\\n', '\n')
            elif os.path.exists(val):
                with open(val, 'rb') as f:
                    pem = f.read().decode()
            break

        if pem:
            self.private_key = serialization.load_pem_private_key(
                pem.encode(), password=None, backend=default_backend()
            )
            log.info("[API] RSA key loaded")
        else:
            log.error("[API] No private key found!")

    def _sign(self, ts: str, method: str, path: str) -> str:
        full = path if path.startswith('/trade-api/v2') else f'/trade-api/v2{path}'
        msg = (ts + method + full.split('?')[0]).encode()
        sig = self.private_key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256()
        )
        return base64.b64encode(sig).decode()

    def _auth_headers(self, method: str, path: str) -> dict:
        ts = str(int(time.time() * 1000))
        return {
            'Content-Type': 'application/json',
            'KALSHI-ACCESS-KEY': self.api_key,
            'KALSHI-ACCESS-SIGNATURE': self._sign(ts, method, path),
            'KALSHI-ACCESS-TIMESTAMP': ts,
        }

    def _request(self, method: str, path: str, body: dict = None,
                 retries: int = 3, timeout: int = 12) -> Optional[dict]:
        """Rate-limited HTTP request with retry."""
        wait = self._min_interval - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait)

        url = f"{self.base_url}/trade-api/v2{path}" if not path.startswith('/trade-api') \
              else f"{self.base_url}{path}"

        for attempt in range(retries):
            try:
                hdrs = self._auth_headers(method, path)
                if method == 'GET':
                    r = self.session.get(url, headers=hdrs, timeout=timeout)
                elif method == 'POST':
                    r = self.session.post(url, headers=hdrs,
                                          data=json.dumps(body or {}), timeout=timeout)
                elif method == 'DELETE':
                    r = self.session.delete(url, headers=hdrs, timeout=timeout)
                else:
                    return None

                self._last_req = time.time()

                if r.status_code in (200, 201):
                    return r.json()
                elif r.status_code == 429:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                elif r.status_code == 409:
                    return {'_error': 'market_not_active', '_code': 409}
                elif r.status_code >= 500:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                else:
                    log.debug(f"[API] {r.status_code}: {r.text[:150]}")
                    return None
            except requests.Timeout:
                time.sleep(1.0)
            except Exception as e:
                log.warning(f"[API] Error: {e}")
                time.sleep(1.0)
        return None

    # ── Auth ──────────────────────────────────────────────────────────────

    def check_auth(self) -> bool:
        r = self._request('GET', '/portfolio/balance')
        if r and 'balance' in r:
            log.info("[API] Auth OK")
            return True
        log.error("[API] Auth FAILED")
        return False

    # ── Balance ───────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """Get available cash balance in dollars."""
        r = self._request('GET', '/portfolio/balance')
        if not r:
            return 0.0
        # Prefer balance_dollars (fixed-point string in dollars)
        if 'balance_dollars' in r:
            return float(r['balance_dollars'])
        # Fallback: 'balance' field is in CENTS (integer)
        if 'balance' in r:
            bal = r['balance']
            if isinstance(bal, (int, float)):
                return bal / 100.0
        return 0.0

    def get_portfolio_value(self) -> float:
        """Get total portfolio value (cash + positions) in dollars."""
        r = self._request('GET', '/portfolio/balance')
        if not r:
            return 0.0
        if 'portfolio_value' in r:
            pv = r['portfolio_value']
            if isinstance(pv, (int, float)):
                return pv / 100.0
        return self.get_balance()

    # ── Markets ───────────────────────────────────────────────────────────

    def get_markets(self, series_ticker: str = None, status: str = 'open',
                    limit: int = 200) -> List[dict]:
        params = [f'limit={limit}']
        if series_ticker:
            params.append(f'series_ticker={series_ticker}')
        if status:
            params.append(f'status={status}')
        r = self._request('GET', '/markets?' + '&'.join(params))
        if r and 'markets' in r:
            return r['markets']
        return []

    def get_market(self, ticker: str) -> Optional[dict]:
        r = self._request('GET', f'/markets/{ticker}')
        if r and 'market' in r:
            return r['market']
        return None

    def get_orderbook(self, ticker: str) -> Optional[dict]:
        r = self._request('GET', f'/markets/{ticker}/orderbook')
        if r and 'orderbook_fp' in r:
            return r['orderbook_fp']
        return None

    def get_multi_orderbooks(self, tickers: List[str]) -> dict:
        """Fetch multiple orderbooks in one call."""
        ticker_str = ','.join(tickers[:40])  # API limit
        r = self._request('GET', f'/markets/orderbooks?tickers={ticker_str}')
        if r and 'orderbooks' in r:
            return r['orderbooks']
        return {}

    # ── Orders (V2 — new endpoint) ───────────────────────────────────────

    def place_order_v2(self, ticker: str, side: str, count: float,
                       price: float, time_in_force: str = 'good_till_canceled',
                       post_only: bool = False) -> Optional[dict]:
        """
        Place order using V2 API.

        Args:
            ticker: Market ticker
            side: 'bid' (buy YES) or 'ask' (buy NO / sell YES)
            count: Number of contracts (float, e.g. 1.0)
            price: Price in dollars (float, e.g. 0.56)
            time_in_force: 'good_till_canceled', 'immediate_or_cancel', 'fill_or_kill'
            post_only: If True, order only rests (maker only, no taker fees)
        """
        body = {
            'ticker': ticker,
            'client_order_id': f'v10_{int(time.time()*1000)}_{random.randint(100,999)}',
            'side': side,
            'count': f'{count:.2f}',
            'price': f'{price:.4f}',
            'time_in_force': time_in_force,
            'self_trade_prevention_type': 'taker_at_cross',
            'post_only': post_only,
        }

        log.info(f"[ORDER] {side.upper()} {ticker} x{count:.2f} @ ${price:.4f} "
                 f"({time_in_force})")

        r = self._request('POST', '/portfolio/events/orders', body=body)
        if r and 'order_id' in r:
            fill = float(r.get('fill_count', '0'))
            remain = float(r.get('remaining_count', '0'))
            avg_price = r.get('average_fill_price', '')
            log.info(f"[ORDER] ✓ {r['order_id'][:8]} | "
                     f"Filled: {fill:.2f} | Remaining: {remain:.2f}"
                     + (f" | Avg: ${avg_price}" if avg_price else ""))
            return r
        elif r and r.get('_code') == 409:
            log.warning(f"[ORDER] Market not active: {ticker}")
            return r
        else:
            log.error(f"[ORDER] Failed: {ticker}")
            return None

    def place_ioc(self, ticker: str, side: str, count: float, price: float) -> Optional[dict]:
        """Place Immediate-Or-Cancel order — fills instantly or cancels."""
        return self.place_order_v2(ticker, side, count, price,
                                   time_in_force='immediate_or_cancel')

    def place_maker(self, ticker: str, side: str, count: float, price: float) -> Optional[dict]:
        """Place post-only maker order — rests on book, no taker fees."""
        return self.place_order_v2(ticker, side, count, price,
                                   time_in_force='good_till_canceled', post_only=True)

    # ── Orders (Legacy V1 — for selling existing positions) ───────────────

    def place_order_v1(self, ticker: str, side: str, action: str,
                       count: int, price: int) -> Optional[dict]:
        """Legacy V1 order (side=yes/no, action=buy/sell, price in cents)."""
        body = {
            'ticker': ticker,
            'client_order_id': f'v10_{int(time.time()*1000)}_{random.randint(100,999)}',
            'side': side.lower(),
            'action': action.lower(),
            'count': count,
            'type': 'limit',
        }
        if side.lower() == 'yes':
            body['yes_price'] = price
        else:
            body['no_price'] = price

        r = self._request('POST', '/portfolio/orders', body=body)
        if r and 'order' in r:
            return r
        return None

    def cancel_order(self, order_id: str) -> bool:
        r = self._request('DELETE', f'/portfolio/orders/{order_id}')
        return r is not None

    # ── Positions ─────────────────────────────────────────────────────────

    def get_positions(self) -> List[dict]:
        r = self._request('GET', '/portfolio/positions?count_filter=position')
        if r and 'market_positions' in r:
            return r['market_positions']
        return []

    # ── Fills ─────────────────────────────────────────────────────────────

    def get_fills(self, limit: int = 50) -> List[dict]:
        r = self._request('GET', f'/portfolio/fills?limit={limit}')
        if r and 'fills' in r:
            return r['fills']
        return []

    # ── WebSocket auth headers ────────────────────────────────────────────

    def ws_headers(self) -> dict:
        """Generate auth headers for WebSocket connection."""
        ts = str(int(time.time() * 1000))
        return {
            'KALSHI-ACCESS-KEY': self.api_key,
            'KALSHI-ACCESS-SIGNATURE': self._sign(ts, 'GET', '/trade-api/ws/v2'),
            'KALSHI-ACCESS-TIMESTAMP': ts,
        }
