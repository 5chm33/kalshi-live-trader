"""Legacy Kalshi API client retained for inspection only.

All writes are blocked in _request; the supported main.py uses public reads.
The old order/position manager is not safe for live trading.
"""

import os
import time
import random
import base64
import json
import logging
import threading
import requests
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from typing import Dict, List, Optional, Callable

from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

log = logging.getLogger('KALSHI')

BASE_URL = "https://external-api.kalshi.com"
WS_URL = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"


class KalshiClient:
    """Synchronous Kalshi REST API client with rate limiting."""

    def __init__(self, config: dict):
        self.api_key = config.get('api_key', '')
        self.base_url = BASE_URL
        self.session = requests.Session()
        self.session.headers.update({'Content-Type': 'application/json'})
        self.private_key = None
        self._last_req = 0.0
        self._min_interval = 0.05  # conservative client pacing; tier budgets are token-based

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
        if method != 'GET':
            raise RuntimeError('Live order writes disabled: unvalidated strategy and position reconciliation')
        wait = self._min_interval - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait)

        url = f"{self.base_url}/trade-api/v2{path}" if not path.startswith('/trade-api') \
              else f"{self.base_url}{path}"

        for attempt in range(retries):
            try:
                hdrs = self._auth_headers(method, path)
                if method == 'GET':
                    r = self.session.get(url, headers=hdrs, timeout=timeout,
                                         allow_redirects=False)
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

    def get_api_limits(self) -> dict:
        """Validate the effective token tier; never infer limits from user claims."""
        data = self._request('GET', '/account/limits')
        if not isinstance(data, dict):
            raise RuntimeError('Cannot verify Kalshi API usage tier')
        tier = data.get('usage_tier')
        if tier not in {'basic', 'advanced', 'expert', 'premier', 'paragon', 'prime', 'prestige'}:
            raise RuntimeError('Unknown Kalshi API usage tier')
        buckets = {}
        for kind in ('read', 'write'):
            value = data.get(kind)
            if not isinstance(value, dict):
                raise RuntimeError(f'Cannot verify {kind} token bucket')
            refill, capacity = value.get('refill_rate'), value.get('bucket_capacity')
            if (isinstance(refill, bool) or isinstance(capacity, bool) or
                    not isinstance(refill, (int, float)) or
                    not isinstance(capacity, (int, float)) or
                    not 0 < refill <= capacity < 1000000):
                raise RuntimeError(f'Invalid {kind} token bucket')
            buckets[kind] = {'refill_rate': refill, 'bucket_capacity': capacity}
        return {'usage_tier': tier, 'read': buckets['read'], 'write': buckets['write']}

    # ── Balance ───────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """Get available cash balance in dollars."""
        r = self._request('GET', '/portfolio/balance')
        if not r:
            raise RuntimeError('Cannot verify Kalshi cash balance')
        # Prefer balance_dollars (fixed-point string in dollars)
        if 'balance_dollars' in r:
            return float(r['balance_dollars'])
        # Fallback: 'balance' field is in CENTS (integer)
        if 'balance' in r:
            bal = r['balance']
            if isinstance(bal, (int, float)):
                return bal / 100.0
        raise RuntimeError('Kalshi cash balance field missing or malformed')

    def get_portfolio_value(self) -> float:
        """Get API portfolio_value (position valuation, excluding available cash)."""
        r = self._request('GET', '/portfolio/balance')
        if not r:
            raise RuntimeError('Cannot verify Kalshi portfolio value')
        if 'portfolio_value' in r:
            pv = r['portfolio_value']
            if isinstance(pv, (int, float)):
                return pv / 100.0
        raise RuntimeError('Kalshi portfolio value field missing or malformed')

    def get_account_snapshot(self) -> dict:
        """Get cash and position mark from the same authenticated response.

        This is a read-only diagnostic, not evidence that trading is safe.
        Never replace absent or erroneous account fields with zero.
        """
        data = self._request('GET', '/portfolio/balance')
        if data is None:
            raise RuntimeError('Cannot verify Kalshi account balance')
        try:
            cash = Decimal(str(data['balance_dollars']))
            value = Decimal(str(data['portfolio_value'])) / 100
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise RuntimeError('Kalshi account balance fields invalid') from exc
        if not cash.is_finite() or not value.is_finite() or cash < 0 or value < 0:
            raise RuntimeError('Kalshi account balance values invalid')
        return {'cash_dollars': str(cash), 'position_mark_dollars': str(value),
                'updated_ts': data.get('updated_ts')}

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
            side: 'bid' (buy YES) or 'ask' (sell YES at a YES price)
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
        r = self._request('GET', '/portfolio/positions?count_filter=position&subaccount=0')
        if r is None or not isinstance(r.get('market_positions'), list):
            raise RuntimeError('Cannot verify live portfolio positions; not an empty portfolio')
        positions = list(r['market_positions'])
        cursor = r.get('cursor')
        seen = set()
        while cursor:
            if cursor in seen or len(seen) >= 100:
                raise RuntimeError('Positions pagination incomplete')
            seen.add(cursor)
            r = self._request('GET', f'/portfolio/positions?count_filter=position&subaccount=0&cursor={quote(str(cursor), safe="")}')
            if r is None or not isinstance(r.get('market_positions'), list):
                raise RuntimeError('Positions pagination failed')
            positions.extend(r['market_positions'])
            cursor = r.get('cursor')
        return positions

    def get_resting_orders(self) -> List[dict]:
        """Read every currently resting order or fail rather than undercount exposure."""
        orders = []
        cursor = None
        seen = set()
        for _ in range(100):
            path = '/portfolio/orders?status=resting&limit=200'
            if cursor:
                path += '&cursor=' + quote(str(cursor), safe='')
            data = self._request('GET', path)
            if data is None or not isinstance(data.get('orders'), list):
                raise RuntimeError('Cannot verify resting orders')
            orders.extend(data['orders'])
            cursor = data.get('cursor')
            if not cursor:
                return orders
            if cursor in seen:
                raise RuntimeError('Resting order pagination cursor loop')
            seen.add(cursor)
        raise RuntimeError('Resting order pagination incomplete')

    def get_orders_by_status(self, ticker: str, status: str) -> List[dict]:
        """Enumerate matching live-tier orders; no absent=flat assumption."""
        if status not in {'resting', 'executed', 'canceled'}:
            raise ValueError('Invalid order status')
        if not ticker or not all(x.isalnum() or x in '-_' for x in ticker):
            raise ValueError('Invalid market ticker')
        orders = []
        seen = set()
        cursor = None
        for _ in range(100):
            path = (f'/portfolio/orders?status={status}&ticker='
                    + quote(ticker, safe='') + '&subaccount=0&limit=200')
            if cursor:
                path += '&cursor=' + quote(str(cursor), safe='')
            data = self._request('GET', path)
            if data is None or not isinstance(data.get('orders'), list):
                raise RuntimeError('Order status GET incomplete')
            orders.extend(data['orders'])
            cursor = data.get('cursor')
            if not cursor:
                return orders
            if cursor in seen:
                raise RuntimeError('Order status cursor loop')
            seen.add(cursor)
        raise RuntimeError('Order status pagination incomplete')

    def get_historical_market_orders(self, ticker: str) -> List[dict]:
        """Read every archived order for a market, with a strict page bound."""
        if not ticker or not all(x.isalnum() or x in '-_' for x in ticker):
            raise ValueError('Invalid market ticker')
        orders = []
        seen = set()
        cursor = None
        for _ in range(100):
            path = '/historical/orders?ticker=' + quote(ticker, safe='') + '&subaccount=0&limit=200'
            if cursor:
                path += '&cursor=' + quote(str(cursor), safe='')
            data = self._request('GET', path)
            if data is None or not isinstance(data.get('orders'), list):
                raise RuntimeError('Historical order GET incomplete')
            orders.extend(data['orders'])
            cursor = data.get('cursor')
            if not cursor:
                return orders
            if cursor in seen:
                raise RuntimeError('Historical order cursor loop')
            seen.add(cursor)
        raise RuntimeError('Historical order pagination incomplete')

    # ── Fills ─────────────────────────────────────────────────────────────

    def get_fills(self, limit: int = 50) -> List[dict]:
        r = self._request('GET', f'/portfolio/fills?limit={limit}')
        if r is None or not isinstance(r.get('fills'), list):
            raise RuntimeError('Cannot verify fills')
        return r['fills']

    def get_market_fills(self, ticker: str, *, historical: bool = False) -> List[dict]:
        """Cursor-complete live or archived fills for one market; no partial result.

        Historical fills lack book_side in their documented shape. Obtain
        direction from the corresponding authenticated order, never guess.
        """
        if not ticker or not all(x.isalnum() or x in '-_' for x in ticker):
            raise ValueError('Invalid market ticker')
        cursor = None
        seen = set()
        fills = []
        for _ in range(100):
            endpoint = '/historical/fills' if historical else '/portfolio/fills'
            path = endpoint + '?ticker=' + quote(ticker, safe='') + '&limit=200'
            if not historical:
                path += '&subaccount=0'
            if cursor:
                path += '&cursor=' + quote(str(cursor), safe='')
            data = self._request('GET', path)
            if data is None or not isinstance(data.get('fills'), list):
                raise RuntimeError('Cannot verify complete market fills')
            fills.extend(data['fills'])
            cursor = data.get('cursor')
            if not cursor:
                return fills
            if cursor in seen:
                raise RuntimeError('Market fills pagination cursor loop')
            seen.add(cursor)
        raise RuntimeError('Market fills pagination incomplete')

    # ── WebSocket auth headers ────────────────────────────────────────────

    def ws_headers(self) -> dict:
        """Generate auth headers for WebSocket connection."""
        ts = str(int(time.time() * 1000))
        return {
            'KALSHI-ACCESS-KEY': self.api_key,
            'KALSHI-ACCESS-SIGNATURE': self._sign(ts, 'GET', '/trade-api/ws/v2'),
            'KALSHI-ACCESS-TIMESTAMP': ts,
        }
