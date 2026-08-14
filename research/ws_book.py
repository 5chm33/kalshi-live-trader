"""Sequence-checked Kalshi WebSocket order-book reconstruction.

This module turns authenticated `orderbook_snapshot` and `orderbook_delta`
messages into the same CanonicalBook used by the paper broker. It cannot submit
an order. A sequence gap raises an exception so callers can request a fresh
snapshot rather than silently trade on a stale book.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from research.models import BookLevel, CanonicalBook, SourceStamp, decimal, payload_hash


class SequenceGap(RuntimeError):
    """A WebSocket delta was received without a contiguous predecessor."""


@dataclass
class _MutableBook:
    ticker: str
    yes_bids: dict[Decimal, Decimal] = field(default_factory=dict)
    no_bids: dict[Decimal, Decimal] = field(default_factory=dict)

    @staticmethod
    def _levels(raw: object) -> dict[Decimal, Decimal]:
        if raw is None:
            return {}
        if not isinstance(raw, list):
            raise ValueError("book levels must be a list")
        levels: dict[Decimal, Decimal] = {}
        for level in raw:
            if not isinstance(level, (list, tuple)) or len(level) != 2:
                raise ValueError(f"invalid level {level!r}")
            price, quantity = decimal(level[0]), decimal(level[1])
            if not (Decimal("0") <= price <= Decimal("1")) or quantity < 0:
                raise ValueError("invalid fixed-point book level")
            if quantity > 0:
                levels[price] = quantity
        return levels

    def replace(self, yes: object, no: object) -> None:
        self.yes_bids = self._levels(yes)
        self.no_bids = self._levels(no)

    def apply_delta(self, side: str, price: object, change: object) -> None:
        levels = self.yes_bids if side == "yes" else self.no_bids if side == "no" else None
        if levels is None:
            raise ValueError(f"unexpected delta side {side!r}")
        px, delta = decimal(price), decimal(change)
        previous = levels.get(px, Decimal("0"))
        updated = previous + delta
        if updated < 0:
            raise ValueError(f"negative depth at {side} {px}: {updated}")
        if updated == 0:
            levels.pop(px, None)
        else:
            levels[px] = updated

    def canonical(self, stamp: SourceStamp) -> CanonicalBook:
        def levels(side: dict[Decimal, Decimal]) -> tuple[BookLevel, ...]:
            return tuple(BookLevel(price=price, quantity=quantity) for price, quantity in sorted(side.items()))
        return CanonicalBook(self.ticker, levels(self.yes_bids), levels(self.no_bids), stamp)


class WebSocketBookSynchronizer:
    """Maintain full books per ticker and validate orderbook sequence numbers."""

    def __init__(self):
        self._books: dict[str, _MutableBook] = {}
        self._last_seq: dict[int, int] = {}

    @staticmethod
    def _stamp(payload: Mapping[str, Any]) -> SourceStamp:
        message = payload.get("msg", {})
        source_at = None
        if isinstance(message, Mapping) and message.get("ts_ms") is not None:
            source_at = datetime.fromtimestamp(int(message["ts_ms"]) / 1000, tz=timezone.utc)
        return SourceStamp(
            source="kalshi_websocket_orderbook",
            source_at=source_at,
            received_at=datetime.now(timezone.utc),
            payload_sha256=payload_hash(payload),
        )

    @staticmethod
    def _message(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        message = payload.get("msg")
        if not isinstance(message, Mapping):
            raise ValueError("WebSocket payload lacks msg object")
        return message

    def _record_seq(self, sid: int, seq: int, is_snapshot: bool) -> None:
        previous = self._last_seq.get(sid)
        if previous is None:
            self._last_seq[sid] = seq
            return
        if is_snapshot:
            if seq < previous:
                raise SequenceGap(f"snapshot seq regression on sid {sid}: {seq} < {previous}")
            self._last_seq[sid] = seq
            return
        if seq != previous + 1:
            raise SequenceGap(f"delta sequence gap on sid {sid}: expected {previous + 1}, received {seq}")
        self._last_seq[sid] = seq

    def apply(self, payload: Mapping[str, Any]) -> CanonicalBook | None:
        """Apply one order-book message and return its post-message book."""
        message_type = str(payload.get("type", ""))
        if message_type not in {"orderbook_snapshot", "orderbook_delta"}:
            return None
        if payload.get("sid") is None or payload.get("seq") is None:
            raise ValueError("order-book payload lacks sid or seq")
        sid, seq = int(payload["sid"]), int(payload["seq"])
        message = self._message(payload)
        ticker = str(message.get("market_ticker", ""))
        if not ticker:
            raise ValueError("order-book payload lacks market_ticker")
        is_snapshot = message_type == "orderbook_snapshot"
        self._record_seq(sid, seq, is_snapshot)
        book = self._books.setdefault(ticker, _MutableBook(ticker))
        if is_snapshot:
            # The official WebSocket schema uses *_dollars_fp. Accept the
            # REST names too so a captured REST snapshot can seed a book.
            book.replace(
                message.get("yes_dollars_fp", message.get("yes_dollars")),
                message.get("no_dollars_fp", message.get("no_dollars")),
            )
        else:
            book.apply_delta(
                str(message.get("side", "")),
                message.get("price_dollars"),
                message.get("delta_fp"),
            )
        return book.canonical(self._stamp(payload))

    def book(self, ticker: str) -> CanonicalBook | None:
        book = self._books.get(ticker)
        if book is None:
            return None
        stamp = SourceStamp(
            source="kalshi_websocket_orderbook_memory",
            source_at=None,
            received_at=datetime.now(timezone.utc),
            payload_sha256="in_memory",
        )
        return book.canonical(stamp)
