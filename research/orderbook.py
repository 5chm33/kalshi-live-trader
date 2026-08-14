"""Canonical fixed-point Kalshi order-book normalization."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from research.models import BookLevel, CanonicalBook, SourceStamp, decimal


def _levels(raw_levels: object) -> tuple[BookLevel, ...]:
    if raw_levels is None:
        return ()
    if not isinstance(raw_levels, list):
        raise ValueError("order-book levels must be a list")
    parsed: list[BookLevel] = []
    for level in raw_levels:
        if not isinstance(level, (list, tuple)) or len(level) != 2:
            raise ValueError(f"invalid order-book level: {level!r}")
        price, quantity = decimal(level[0]), decimal(level[1])
        if not (Decimal("0") <= price <= Decimal("1")):
            raise ValueError(f"price outside [0,1]: {price}")
        if quantity <= 0:
            raise ValueError(f"nonpositive book quantity: {quantity}")
        parsed.append(BookLevel(price=price, quantity=quantity))
    # Kalshi documents ascending price; sorting protects downstream logic when
    # an upstream payload arrives out of order.
    return tuple(sorted(parsed, key=lambda x: x.price))


def parse_orderbook(ticker: str, payload: Mapping[str, Any], stamp: SourceStamp) -> CanonicalBook:
    """Parse the `orderbook_fp` response into a canonical binary book."""
    raw = payload.get("orderbook_fp")
    if not isinstance(raw, Mapping):
        raise ValueError("missing orderbook_fp in Kalshi response")
    return CanonicalBook(
        ticker=ticker,
        yes_bids=_levels(raw.get("yes_dollars")),
        no_bids=_levels(raw.get("no_dollars")),
        stamp=stamp,
    )
