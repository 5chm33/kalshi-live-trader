"""Decimal-safe data contracts for the V11 paper-trading system.

No class in this module submits, cancels, or modifies an exchange order.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from json import dumps
from typing import Any, Mapping, Sequence

MONEY_QUANTUM = Decimal("0.0001")
ONE = Decimal("1")
ZERO = Decimal("0")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def decimal(value: Any) -> Decimal:
    """Convert API fixed-point values to Decimal without floating-point loss."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def payload_hash(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    """Stable SHA-256 hash for an externally sourced payload."""
    canonical = dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceStamp:
    """Time and provenance for an external observation."""
    source: str
    received_at: datetime
    source_at: datetime | None
    payload_sha256: str

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["received_at"] = self.received_at.isoformat()
        row["source_at"] = self.source_at.isoformat() if self.source_at else None
        return row


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class CanonicalBook:
    """Kalshi binary book normalized to the YES-leg price scale.

    yes_bids and no_bids contain only resting bids, each sorted ascending by
    price as returned by the exchange. An incoming long YES takes NO bids at
    `1 - no_bid`; an incoming long NO takes YES bids at `1 - yes_bid`.
    """
    ticker: str
    yes_bids: tuple[BookLevel, ...]
    no_bids: tuple[BookLevel, ...]
    stamp: SourceStamp

    @property
    def best_yes_bid(self) -> Decimal | None:
        return self.yes_bids[-1].price if self.yes_bids else None

    @property
    def best_no_bid(self) -> Decimal | None:
        return self.no_bids[-1].price if self.no_bids else None

    @property
    def best_yes_ask(self) -> Decimal | None:
        return ONE - self.best_no_bid if self.best_no_bid is not None else None

    @property
    def best_no_ask(self) -> Decimal | None:
        return ONE - self.best_yes_bid if self.best_yes_bid is not None else None

    @property
    def yes_spread(self) -> Decimal | None:
        if self.best_yes_bid is None or self.best_yes_ask is None:
            return None
        return self.best_yes_ask - self.best_yes_bid


@dataclass(frozen=True)
class PaperOrder:
    paper_order_id: str
    strategy_version: str
    ticker: str
    outcome_side: str  # "yes" or "no"
    requested_contracts: Decimal
    limit_price: Decimal
    signal_probability: Decimal
    expected_edge_before_cost: Decimal
    created_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperFill:
    paper_order_id: str
    ticker: str
    outcome_side: str
    filled_contracts: Decimal
    average_price: Decimal
    position_cost: Decimal
    estimated_fee: Decimal
    estimated_rounding_reserve: Decimal
    total_debit: Decimal
    model: str
    created_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategySignal:
    """A research candidate. It is not an order instruction."""
    signal_id: str
    strategy: str
    strategy_version: str
    ticker: str
    outcome_side: str
    model_probability: Decimal
    conservative_probability: Decimal
    observed_price: Decimal
    requested_contracts: Decimal
    source_stamp: SourceStamp
    rationale: str
    features: Mapping[str, Any]

    @property
    def gross_edge(self) -> Decimal:
        if self.outcome_side == "yes":
            return self.conservative_probability - self.observed_price
        return (ONE - self.conservative_probability) - self.observed_price


@dataclass(frozen=True)
class GameState:
    source_game_id: str
    league: str
    status: str
    away_team: str
    home_team: str
    away_runs: int
    home_runs: int
    inning: int | None
    inning_half: str | None
    scheduled_innings: int | None
    stamp: SourceStamp
    raw: Mapping[str, Any]

    @property
    def lead(self) -> int:
        return self.home_runs - self.away_runs

    @property
    def leader(self) -> str | None:
        if self.lead > 0:
            return self.home_team
        if self.lead < 0:
            return self.away_team
        return None


@dataclass(frozen=True)
class MarketMapping:
    source_game_id: str
    ticker: str
    team: str
    confidence: Decimal
    mapping_method: str
    created_at: datetime


def normalize_team(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())
