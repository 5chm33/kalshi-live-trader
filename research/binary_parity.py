"""Paper-only same-ticker YES/NO parity research.

A binary market pays exactly one dollar across one YES and one NO contract at
settlement.  This module evaluates whether *displayed opposite-side depth* in a
single book snapshot would have allowed a matched paper purchase below that
locked payout after estimated fees and conservative rounding/atomicity reserves.
It has no exchange client and cannot submit orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from research.fees import conservative_rounding_reserve, estimate_fee
from research.models import BookLevel, CanonicalBook, ONE, ZERO, decimal


@dataclass(frozen=True)
class ParityAssessment:
    ticker: str
    requested_contracts: Decimal
    matched_contracts: Decimal
    yes_average_price: Decimal
    no_average_price: Decimal
    yes_fee: Decimal
    no_fee: Decimal
    total_debit: Decimal
    locked_payout: Decimal
    net_locked_value: Decimal
    status: str
    rationale: str

    @property
    def is_candidate(self) -> bool:
        return self.status == "candidate"


def _asks(book: CanonicalBook, outcome_side: str) -> tuple[BookLevel, ...]:
    if outcome_side == "yes":
        return tuple(BookLevel(ONE - level.price, level.quantity) for level in reversed(book.no_bids))
    if outcome_side == "no":
        return tuple(BookLevel(ONE - level.price, level.quantity) for level in reversed(book.yes_bids))
    raise ValueError("outcome_side must be yes or no")


def _walk(levels: tuple[BookLevel, ...], requested: Decimal) -> tuple[Decimal, Decimal]:
    remaining, filled, cost = requested, ZERO, ZERO
    for level in levels:
        if remaining <= ZERO:
            break
        take = min(remaining, level.quantity)
        filled += take
        cost += take * level.price
        remaining -= take
    return (filled, cost / filled) if filled > ZERO else (ZERO, ZERO)


def assess_complement_parity(
    book: CanonicalBook,
    requested_contracts: Decimal | str = Decimal("1"),
    fee_multiplier: Decimal | str = Decimal("1"),
    atomicity_reserve_per_contract: Decimal | str = Decimal("0.01"),
    min_locked_profit_per_contract: Decimal | str = Decimal("0.005"),
) -> ParityAssessment:
    """Assess a matched *paper* buy of YES and NO using one book snapshot.

    The atomicity reserve deliberately treats a two-leg snapshot as less
    favorable than a truly simultaneous exchange fill.  A candidate is a
    research observation only and does not authorize any order.
    """
    request = decimal(requested_contracts)
    multiplier = decimal(fee_multiplier)
    atomicity_reserve = decimal(atomicity_reserve_per_contract)
    minimum = decimal(min_locked_profit_per_contract)
    if request <= ZERO or multiplier <= ZERO or atomicity_reserve < ZERO or minimum < ZERO:
        raise ValueError("invalid parity assessment parameters")

    yes_levels, no_levels = _asks(book, "yes"), _asks(book, "no")
    yes_available, _ = _walk(yes_levels, request)
    no_available, _ = _walk(no_levels, request)
    matched = min(yes_available, no_available)
    if matched <= ZERO:
        return ParityAssessment(book.ticker, request, ZERO, ZERO, ZERO, ZERO, ZERO, ZERO, ZERO, ZERO,
                                "ineligible_no_two_sided_depth", "Both complement legs require displayed opposite-side depth.")
    if matched < request:
        return ParityAssessment(book.ticker, request, matched, ZERO, ZERO, ZERO, ZERO, ZERO, ZERO, ZERO,
                                "ineligible_partial_matched_depth", "Requested matched size is not fully available on both legs.")

    _, yes_price = _walk(yes_levels, matched)
    _, no_price = _walk(no_levels, matched)
    yes_fee = estimate_fee(yes_price, matched, multiplier, "taker")
    no_fee = estimate_fee(no_price, matched, multiplier, "taker")
    rounding = conservative_rounding_reserve(matched) * Decimal("2")
    total_debit = (yes_price + no_price) * matched + yes_fee + no_fee + rounding + (atomicity_reserve * matched)
    payout = matched
    net = payout - total_debit
    status = "candidate" if net >= minimum * matched else "not_profitable_after_costs"
    rationale = (
        "single-snapshot complement parity survives fees, rounding, and atomicity reserve"
        if status == "candidate"
        else "combined complement purchase does not clear the conservative net-profit threshold"
    )
    return ParityAssessment(
        ticker=book.ticker, requested_contracts=request, matched_contracts=matched,
        yes_average_price=yes_price, no_average_price=no_price, yes_fee=yes_fee, no_fee=no_fee,
        total_debit=total_debit, locked_payout=payout, net_locked_value=net, status=status, rationale=rationale,
    )
