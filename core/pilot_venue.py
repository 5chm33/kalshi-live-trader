"""Small supervised Kalshi execution adapter for one numbered subaccount.

Never imported by the legacy bot. GETs may retry through KalshiClient; an order
POST is sent at most once and any uncertain response must be reconciled by ID.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from core.kalshi_client import KalshiClient

TICKER = re.compile(r"^[A-Z0-9_-]{4,120}$")
ORDER_ID = re.compile(r"^[A-Za-z0-9_-]{4,128}$")
MLB_SHARD = 3  # Official Kalshi exchange-sharding guide, current KXMLBGAME metadata.


class VenueError(RuntimeError):
    pass


def money(value, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise VenueError(f"Invalid {field}")
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise VenueError(f"Invalid {field}") from None
    if not number.is_finite():
        raise VenueError(f"Non-finite {field}")
    return number


class ScopedVenue:
    def __init__(self, config: dict, subaccount: int):
        if isinstance(subaccount, bool) or not isinstance(subaccount, int) or not 1 <= subaccount <= 63:
            raise ValueError("A distinct numbered subaccount is required")
        self.subaccount = subaccount
        self.client = KalshiClient(config)
        if not self.client.api_key or not self.client.private_key:
            raise VenueError("Kalshi authentication not provisioned")

    def get(self, path: str) -> dict:
        if not path.startswith('/') or '//' in path or '\n' in path:
            raise ValueError("Unsafe GET path")
        data = self.client._request('GET', path)
        if not isinstance(data, dict) or '_error' in data:
            raise VenueError("Authenticated GET failed; stop execution")
        return data

    def cash(self) -> Decimal:
        data = self.get(f'/portfolio/balance?subaccount={self.subaccount}&exchange_index={MLB_SHARD}')
        cash = money(data.get('balance_dollars'), 'subaccount balance_dollars')
        if cash < 0:
            raise VenueError("Negative subaccount cash")
        return cash

    def pages(self, endpoint: str, field: str, params: str) -> list[dict]:
        results, cursor, seen = [], None, set()
        for _ in range(100):
            path = f'{endpoint}?{params}&limit=200'
            if cursor:
                path += '&cursor=' + quote(str(cursor), safe='')
            page = self.get(path)
            chunk = page.get(field)
            if not isinstance(chunk, list) or any(not isinstance(item, dict) for item in chunk):
                raise VenueError(f"Missing {field} page")
            results.extend(chunk)
            cursor = page.get('cursor')
            if not cursor:
                return results
            if cursor in seen:
                raise VenueError(f"Repeated {field} cursor")
            seen.add(cursor)
        raise VenueError(f"Incomplete {field} pages")

    def positions(self) -> list[dict]:
        rows = self.pages('/portfolio/positions', 'market_positions',
                          f'count_filter=position&subaccount={self.subaccount}&exchange_index={MLB_SHARD}')
        for row in rows:
            if ('subaccount_number' in row and row['subaccount_number'] != self.subaccount):
                raise VenueError("Position belongs to another subaccount")
            if row.get('exchange_index') != MLB_SHARD:
                raise VenueError("Position belongs to wrong exchange shard")
            value = money(row.get('position_fp'), 'position_fp')
            if value == 0 or not TICKER.fullmatch(str(row.get('ticker', ''))):
                raise VenueError("Unverifiable position")
        if len({row['ticker'] for row in rows}) != len(rows):
            raise VenueError("Duplicate market position")
        return rows

    def orders(self, *, status: str, ticker: str | None = None) -> list[dict]:
        if status not in {'resting', 'canceled', 'executed'}:
            raise ValueError("Unsupported status")
        params = f'status={status}&subaccount={self.subaccount}&exchange_index={MLB_SHARD}'
        if ticker is not None:
            if not TICKER.fullmatch(ticker):
                raise ValueError("Invalid ticker")
            params += '&ticker=' + quote(ticker, safe='')
        rows = self.pages('/portfolio/orders', 'orders', params)
        if any(row.get('subaccount_number') != self.subaccount or row.get('exchange_index') != MLB_SHARD for row in rows):
            raise VenueError("Order belongs to another subaccount or is unscoped")
        return rows

    def fills(self, ticker: str, order_id: str) -> list[dict]:
        if not TICKER.fullmatch(ticker) or not ORDER_ID.fullmatch(order_id):
            raise ValueError("Invalid ticker or order ID")
        rows = self.pages('/portfolio/fills', 'fills',
                          f'ticker={quote(ticker, safe="")}&subaccount={self.subaccount}&exchange_index={MLB_SHARD}')
        if any(row.get('subaccount_number') != self.subaccount or row.get('exchange_index') != MLB_SHARD for row in rows):
            raise VenueError("Fill belongs to another subaccount or is unscoped")
        matches = [row for row in rows if row.get('order_id') == order_id]
        ids = [row.get('fill_id') for row in matches]
        if any(not value for value in ids) or len(ids) != len(set(ids)):
            raise VenueError("Missing or duplicate fill IDs")
        return matches

    def submit_ioc(self, payload: dict) -> dict:
        """Exactly one POST. A timeout, redirect, or malformed ACK is *uncertain*."""
        if (not isinstance(payload, dict) or payload.get('subaccount') != self.subaccount
                or payload.get('exchange_index') != MLB_SHARD
                or payload.get('time_in_force') != 'immediate_or_cancel'
                or payload.get('count') != '1.00'
                or payload.get('post_only') is not False
                or payload.get('cancel_order_on_pause') is not True
                or payload.get('self_trade_prevention_type') != 'taker_at_cross'
                or not TICKER.fullmatch(str(payload.get('ticker', '')))
                or not ORDER_ID.fullmatch(str(payload.get('client_order_id', '')))
                or payload.get('side') not in {'bid', 'ask'}
                or (payload.get('side') == 'ask') != (payload.get('reduce_only') is True)
                or not 0 < money(payload.get('price'), 'YES limit') < 1
                or (payload.get('side') == 'bid' and money(payload.get('price'), 'YES limit') > Decimal('0.50'))):
            raise VenueError("Unapproved IOC payload")
        path = '/portfolio/events/orders'
        headers = self.client._auth_headers('POST', path)
        # No automatic retry, no redirect, strict TLS. The caller persists the
        # submitting intent BEFORE reaching this boundary.
        try:
            response = self.client.session.post(self.client.base_url + '/trade-api/v2' + path,
                                                json=payload, headers=headers,
                                                timeout=8, allow_redirects=False, verify=True)
        except Exception as exc:
            raise VenueError(f"Order submission uncertain: {type(exc).__name__}") from None
        if response.status_code not in (200, 201):
            raise VenueError(f"Order submission uncertain: HTTP {response.status_code}")
        try:
            result = response.json()
        except (ValueError, TypeError):
            raise VenueError("Order submission uncertain: malformed acknowledgement") from None
        if not isinstance(result, dict):
            raise VenueError("Order submission uncertain: invalid acknowledgement")
        return result

    def cancel_owned_resting(self, order: dict, client_order_id: str) -> None:
        if (not isinstance(order, dict) or order.get('subaccount_number') != self.subaccount
                or order.get('status') != 'resting' or order.get('exchange_index') != MLB_SHARD
                or order.get('client_order_id') != client_order_id
                or not ORDER_ID.fullmatch(str(order.get('order_id', '')))
                or not TICKER.fullmatch(str(order.get('ticker', '')))):
            raise VenueError("Cannot cancel order not proven to be pilot-owned and resting")
        ident, ticker = order['order_id'], order['ticker']
        path = (f'/portfolio/events/orders/{ident}?subaccount={self.subaccount}'
                f'&exchange_index={MLB_SHARD}&market_ticker={quote(ticker, safe="")}')
        headers = self.client._auth_headers('DELETE', path)
        try:
            response = self.client.session.delete(self.client.base_url + '/trade-api/v2' + path,
                                                  headers=headers, timeout=8,
                                                  allow_redirects=False, verify=True)
        except Exception as exc:
            raise VenueError(f"Pilot-owned cancel outcome uncertain: {type(exc).__name__}") from None
        if response.status_code not in (200, 201):
            raise VenueError(f"Pilot-owned cancel outcome uncertain: HTTP {response.status_code}")
        try:
            data = response.json()
        except (ValueError, TypeError):
            raise VenueError("Pilot-owned cancel outcome uncertain: malformed response") from None
        if (not isinstance(data, dict) or data.get('order_id') != ident
                or data.get('client_order_id') != client_order_id):
            raise VenueError("Pilot-owned cancel outcome uncertain: identity mismatch")
