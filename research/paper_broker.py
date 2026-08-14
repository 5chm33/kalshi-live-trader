"""Deterministic paper-execution engine.

The broker has no exchange client dependency and cannot send network requests.
It fills a simulated marketable order only against displayed opposite-side depth.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from research.fees import conservative_rounding_reserve, estimate_fee
from research.models import (
    CanonicalBook,
    ONE,
    ZERO,
    BookLevel,
    PaperFill,
    PaperOrder,
    StrategySignal,
    decimal,
)


class PaperBroker:
    """Fee-aware paper broker for binary Kalshi books."""

    def __init__(self, fee_multiplier: Decimal | str = Decimal("1")):
        self.fee_multiplier = decimal(fee_multiplier)

    @staticmethod
    def _opposite_levels(book: CanonicalBook, outcome_side: str) -> tuple[BookLevel, ...]:
        if outcome_side == "yes":
            # YES market buy consumes NO bids. Convert each to YES-leg ask price.
            return tuple(
                BookLevel(price=ONE - level.price, quantity=level.quantity)
                for level in reversed(book.no_bids)
            )
        if outcome_side == "no":
            # NO market buy consumes YES bids. Convert each to NO-leg ask price.
            return tuple(
                BookLevel(price=ONE - level.price, quantity=level.quantity)
                for level in reversed(book.yes_bids)
            )
        raise ValueError("outcome_side must be 'yes' or 'no'")

    @staticmethod
    def _walk(levels: tuple[BookLevel, ...], requested: Decimal, limit: Decimal) -> tuple[Decimal, Decimal]:
        """Return (filled contracts, volume-weighted price), respecting limit."""
        remaining = requested
        total_cost = ZERO
        filled = ZERO
        for level in levels:
            if level.price > limit or remaining <= ZERO:
                break
            take = min(remaining, level.quantity)
            total_cost += take * level.price
            filled += take
            remaining -= take
        if filled <= ZERO:
            return ZERO, ZERO
        return filled, total_cost / filled

    def propose(self, signal: StrategySignal, limit_price: Decimal | str | None = None) -> PaperOrder:
        price = decimal(limit_price) if limit_price is not None else signal.observed_price
        return PaperOrder(
            paper_order_id=f"paper-{uuid4()}",
            strategy_version=signal.strategy_version,
            ticker=signal.ticker,
            outcome_side=signal.outcome_side,
            requested_contracts=signal.requested_contracts,
            limit_price=price,
            signal_probability=signal.conservative_probability,
            expected_edge_before_cost=signal.gross_edge,
            created_at=datetime.now(timezone.utc),
            metadata={"signal_id": signal.signal_id, "mode": "paper"},
        )

    def execute(self, order: PaperOrder, book: CanonicalBook) -> PaperFill | None:
        """Paper-fill an order using only depth displayed at the snapshot time."""
        if order.ticker != book.ticker:
            raise ValueError("order ticker and book ticker differ")
        levels = self._opposite_levels(book, order.outcome_side)
        filled, avg_price = self._walk(levels, order.requested_contracts, order.limit_price)
        if filled <= ZERO:
            return None

        fee = estimate_fee(avg_price, filled, self.fee_multiplier, "taker")
        rounding = conservative_rounding_reserve(filled)
        cost = avg_price * filled
        return PaperFill(
            paper_order_id=order.paper_order_id,
            ticker=order.ticker,
            outcome_side=order.outcome_side,
            filled_contracts=filled,
            average_price=avg_price,
            position_cost=cost,
            estimated_fee=fee,
            estimated_rounding_reserve=rounding,
            total_debit=cost + fee + rounding,
            model="displayed_depth_taker_v1",
            created_at=datetime.now(timezone.utc),
            metadata={
                "book_payload_sha256": book.stamp.payload_sha256,
                "limit_price": str(order.limit_price),
                "partial_fill": str(filled < order.requested_contracts).lower(),
            },
        )
