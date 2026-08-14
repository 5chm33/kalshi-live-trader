"""Paper-only mutually-exclusive NO-basket research.

If an event is API-marked mutually exclusive, at most one market can resolve YES.
A matched purchase of NO on K distinct markets therefore has a minimum payout of
K-1 contracts, even if all markets resolve NO. This module tests that *documented
structural lower bound* against displayed depth and conservative cost reserves.
It has no network or order capability.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Mapping

from research.binary_parity import _asks, _walk
from research.fees import conservative_rounding_reserve, estimate_fee
from research.models import CanonicalBook, ONE, ZERO, decimal


@dataclass(frozen=True)
class MecNoBasketAssessment:
    event_ticker: str
    tickers: tuple[str, ...]
    requested_contracts: Decimal
    matched_contracts: Decimal
    leg_prices: tuple[Decimal, ...]
    estimated_fees: tuple[Decimal, ...]
    total_debit: Decimal
    guaranteed_payout_floor: Decimal
    net_locked_value: Decimal
    status: str
    rationale: str

    @property
    def is_candidate(self) -> bool:
        return self.status == "candidate"


def assess_mec_no_basket(
    event_ticker: str,
    books: Mapping[str, CanonicalBook],
    requested_contracts: Decimal | str = Decimal("1"),
    fee_multiplier: Decimal | str = Decimal("1"),
    atomicity_reserve_per_leg_contract: Decimal | str = Decimal("0.01"),
    min_locked_profit_per_contract: Decimal | str = Decimal("0.005"),
    max_legs: int = 6,
) -> tuple[MecNoBasketAssessment, ...]:
    """Return all cost-ordered K-leg paper assessments for K>=2.

    Only API event metadata can establish mutual exclusivity; callers must
    enforce that before invoking this function. Every assessment is explicitly
    non-executable because simultaneous multi-leg fill is not guaranteed.
    """
    requested, multiplier = decimal(requested_contracts), decimal(fee_multiplier)
    atomicity, minimum = decimal(atomicity_reserve_per_leg_contract), decimal(min_locked_profit_per_contract)
    if requested <= ZERO or multiplier <= ZERO or atomicity < ZERO or minimum < ZERO or max_legs < 2:
        raise ValueError("invalid MEC basket parameters")

    legs = []
    for ticker, book in books.items():
        available, price = _walk(_asks(book, "no"), requested)
        if available >= requested:
            legs.append((ticker, price))
    legs.sort(key=lambda item: item[1])
    assessments = []
    for size in range(2, min(max_legs, len(legs)) + 1):
        # With fixed requested size and a min payout that rises linearly by one
        # per added NO leg, the k cheapest legs are the only cost-minimizing
        # candidate for each basket size.
        selected = legs[:size]
        prices = tuple(price for _, price in selected)
        fees = tuple(estimate_fee(price, requested, multiplier, "taker") for price in prices)
        total = sum((price * requested for price in prices), ZERO) + sum(fees, ZERO)
        total += conservative_rounding_reserve(requested) * Decimal(size)
        total += atomicity * requested * Decimal(size)
        floor = Decimal(size - 1) * requested
        net = floor - total
        status = "candidate" if net >= minimum * requested else "not_profitable_after_costs"
        assessments.append(MecNoBasketAssessment(
            event_ticker=event_ticker, tickers=tuple(ticker for ticker, _ in selected),
            requested_contracts=requested, matched_contracts=requested, leg_prices=prices,
            estimated_fees=fees, total_debit=total, guaranteed_payout_floor=floor,
            net_locked_value=net, status=status,
            rationale=(
                "API mutually-exclusive NO basket clears modeled fees, depth and multi-leg atomicity reserve"
                if status == "candidate" else
                "NO basket does not clear the conservative fee/depth/atomicity threshold"
            ),
        ))
    return tuple(assessments)
