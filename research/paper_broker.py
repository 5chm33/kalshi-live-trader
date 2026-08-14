"""Deterministic paper-execution engine.

The broker has no exchange client dependency and cannot send network requests.
It fills a simulated marketable order only against displayed opposite-side depth.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from research.execution_realism import TakerExecutionPolicy
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

    def __init__(self, fee_multiplier: Decimal | str = Decimal("1"), execution_policy: TakerExecutionPolicy | None = None):
        self.fee_multiplier = decimal(fee_multiplier)
        self.execution_policy = execution_policy

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

    def execute(self, order: PaperOrder, book: CanonicalBook, decision_at: datetime | None = None) -> PaperFill | None:
        """Paper-fill a marketable/taker order against displayed depth.

        When a TakerExecutionPolicy is supplied, an over-age snapshot is rejected
        and each displayed price receives a conservative latency haircut. Maker
        orders, queue position, and partial-fill waiting are intentionally not
        represented by this model.
        """
        if order.ticker != book.ticker:
            raise ValueError("order ticker and book ticker differ")
        policy_metadata: dict[str, str] = {}
        levels = self._opposite_levels(book, order.outcome_side)
        if self.execution_policy is not None:
            if not self.execution_policy.is_fresh(book, decision_at):
                return None
            haircut = self.execution_policy.adverse_price_haircut
            levels = tuple(
                BookLevel(price=min(ONE, level.price + haircut), quantity=level.quantity)
                for level in levels
            )
            policy_metadata = self.execution_policy.metadata(book, decision_at)
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
                **policy_metadata,
            },
        )
