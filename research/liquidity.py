"""Liquidity and coverage filters based on actual normalized book observations."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Iterable

from research.models import CanonicalBook


@dataclass(frozen=True)
class LiquidityPolicy:
    minimum_observations: int
    maximum_spread: Decimal
    minimum_top_of_book_contracts: Decimal
    required_contracts: Decimal


def _ask_and_depth(book: CanonicalBook, outcome_side: str) -> tuple[Decimal | None, Decimal]:
    levels = book.no_bids if outcome_side == "yes" else book.yes_bids if outcome_side == "no" else ()
    if not levels:
        return None, Decimal("0")
    best = levels[-1]
    return Decimal("1") - best.price, best.quantity


def liquidity_report(books: Iterable[CanonicalBook], outcome_side: str, policy: LiquidityPolicy) -> dict[str, object]:
    rows: list[tuple[Decimal, Decimal, Decimal]] = []
    for book in books:
        bid = book.best_yes_bid if outcome_side == "yes" else book.best_no_bid if outcome_side == "no" else None
        ask, depth = _ask_and_depth(book, outcome_side)
        if bid is None or ask is None:
            continue
        rows.append((ask - bid, depth, ask))
    failures: list[str] = []
    if len(rows) < policy.minimum_observations:
        failures.append("insufficient_book_observations")
    if not rows:
        return {"eligible": False, "failures": failures + ["no_two_sided_books"], "observations": 0}
    spreads, depths, asks = zip(*rows)
    median_spread = Decimal(str(median(spreads)))
    median_depth = Decimal(str(median(depths)))
    if median_spread > policy.maximum_spread:
        failures.append("spread_too_wide")
    if median_depth < policy.minimum_top_of_book_contracts or median_depth < policy.required_contracts:
        failures.append("insufficient_top_of_book_depth")
    return {
        "eligible": not failures,
        "failures": failures,
        "observations": len(rows),
        "median_spread": str(median_spread),
        "median_top_of_book_depth": str(median_depth),
        "median_executable_ask": str(Decimal(str(median(asks)))),
        "outcome_side": outcome_side,
        "execution_scope": "taker_only_displayed_depth",
    }
