"""Paper-only directional threshold-cover research.

For two contracts on the exact same underlying event where YES on a lower
threshold and NO on a higher threshold cover every possible settlement value,
this module evaluates whether a matched displayed-depth purchase would lock at
least one dollar before considering execution risk. It never contacts Kalshi.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping

from research.binary_parity import _asks, _walk
from research.fees import conservative_rounding_reserve, estimate_fee
from research.models import CanonicalBook, ONE, ZERO, decimal


@dataclass(frozen=True)
class DirectionalCoverAssessment:
    lower_ticker: str
    upper_ticker: str
    lower_floor: Decimal
    upper_floor: Decimal
    requested_contracts: Decimal
    matched_contracts: Decimal
    lower_yes_price: Decimal
    upper_no_price: Decimal
    total_debit: Decimal
    guaranteed_payout_floor: Decimal
    net_locked_value: Decimal
    status: str
    rationale: str

    @property
    def is_candidate(self) -> bool:
        return self.status == "candidate"


def is_directional_upper_tail(market: Mapping[str, object]) -> bool:
    """Require API strike metadata for an unbounded upper-tail binary contract."""
    return (
        str(market.get("market_type", "")) == "binary"
        and market.get("floor_strike") is not None
        and market.get("cap_strike") is None
        and str(market.get("status", "")).lower() in {"open", "active"}
    )


def assess_directional_cover(
    lower_book: CanonicalBook,
    upper_book: CanonicalBook,
    lower_floor: Decimal | str,
    upper_floor: Decimal | str,
    requested_contracts: Decimal | str = Decimal("1"),
    fee_multiplier: Decimal | str = Decimal("1"),
    atomicity_reserve_per_contract: Decimal | str = Decimal("0.01"),
    min_locked_profit_per_contract: Decimal | str = Decimal("0.005"),
) -> DirectionalCoverAssessment:
    lower, upper, requested = decimal(lower_floor), decimal(upper_floor), decimal(requested_contracts)
    multiplier, atomicity, minimum = decimal(fee_multiplier), decimal(atomicity_reserve_per_contract), decimal(min_locked_profit_per_contract)
    if lower >= upper:
        raise ValueError("lower threshold must be strictly below upper threshold")
    if requested <= ZERO or multiplier <= ZERO or atomicity < ZERO or minimum < ZERO:
        raise ValueError("invalid directional-cover parameters")

    # Long YES at lower floor and long NO at upper floor guarantee at least one
    # payout as long as both API strike fields refer to the same underlying event.
    lower_levels, upper_levels = _asks(lower_book, "yes"), _asks(upper_book, "no")
    lower_available, _ = _walk(lower_levels, requested)
    upper_available, _ = _walk(upper_levels, requested)
    matched = min(lower_available, upper_available)
    if matched <= ZERO:
        return DirectionalCoverAssessment(lower_book.ticker, upper_book.ticker, lower, upper, requested, ZERO, ZERO, ZERO, ZERO, ZERO, ZERO, "ineligible_no_two_sided_depth", "Both structural legs need displayed opposite-side depth.")
    if matched < requested:
        return DirectionalCoverAssessment(lower_book.ticker, upper_book.ticker, lower, upper, requested, matched, ZERO, ZERO, ZERO, ZERO, ZERO, "ineligible_partial_matched_depth", "Requested matched size is not available on both structural legs.")

    _, lower_price = _walk(lower_levels, matched)
    _, upper_price = _walk(upper_levels, matched)
    lower_fee = estimate_fee(lower_price, matched, multiplier, "taker")
    upper_fee = estimate_fee(upper_price, matched, multiplier, "taker")
    total = (lower_price + upper_price) * matched + lower_fee + upper_fee + conservative_rounding_reserve(matched) * Decimal("2") + atomicity * matched
    payout = matched
    net = payout - total
    status = "candidate" if net >= minimum * matched else "not_profitable_after_costs"
    rationale = (
        "same-event lower-YES plus upper-NO structural cover clears all modeled costs"
        if status == "candidate"
        else "directional cover does not clear the conservative fee/depth/atomicity threshold"
    )
    return DirectionalCoverAssessment(lower_book.ticker, upper_book.ticker, lower, upper, requested, matched, lower_price, upper_price, total, payout, net, status, rationale)
