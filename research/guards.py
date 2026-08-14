"""Safety and eligibility gates for V11 research.

The V11 system is deliberately paper-only. These guards are pure functions so
that strategy code cannot bypass them by accident.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

POLITICAL_KEYWORDS = frozenset({
    "election", "president", "presidential", "governor", "senate", "senator",
    "congress", "congressional", "democrat", "republican", "primary", "ballot",
    "referendum", "nominee", "nomination", "cabinet", "political", "politics", "vote",
})


@dataclass(frozen=True)
class Eligibility:
    allowed: bool
    reason: str


def is_political_market(market: Mapping[str, object]) -> bool:
    """Conservative political market classifier using only supplied metadata."""
    text = " ".join(
        str(market.get(key, ""))
        for key in ("ticker", "event_ticker", "title", "subtitle", "category", "series_ticker")
    ).lower()
    return any(keyword in text for keyword in POLITICAL_KEYWORDS)


def paper_only_guard(requested_mode: str) -> Eligibility:
    """V11 refuses any mode other than paper during the research program."""
    if requested_mode.lower() != "paper":
        return Eligibility(False, "research system is hard-locked to PAPER mode")
    return Eligibility(True, "paper mode enabled")


def market_eligibility(market: Mapping[str, object], allowed_series: Iterable[str]) -> Eligibility:
    """Require active status, explicit strategy allowlist, and non-political content."""
    if is_political_market(market):
        return Eligibility(False, "political/election market blocked")

    status = str(market.get("status", "")).lower()
    if status != "open":
        return Eligibility(False, f"market status is {status or 'unknown'}, not open")

    series = str(market.get("series_ticker", ""))
    if series not in set(allowed_series):
        return Eligibility(False, f"series {series or 'unknown'} is not allowlisted")

    return Eligibility(True, "eligible")
