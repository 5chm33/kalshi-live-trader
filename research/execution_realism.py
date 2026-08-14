"""Conservative paper-only execution assumptions.

This module models only marketable/taker paper entries. Maker, queue-position, and
partial-fill-timeout assumptions are deliberately separate and unsupported here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from research.models import CanonicalBook, decimal


@dataclass(frozen=True)
class TakerExecutionPolicy:
    max_book_age_seconds: Decimal = Decimal("1")
    latency_seconds: Decimal = Decimal("0.250")
    adverse_price_per_second: Decimal = Decimal("0.002")
    partial_fill_timeout_seconds: Decimal = Decimal("0")

    def validate(self) -> None:
        if self.max_book_age_seconds < 0 or self.latency_seconds < 0 or self.adverse_price_per_second < 0:
            raise ValueError("execution-policy durations and haircut must be non-negative")
        if self.partial_fill_timeout_seconds != 0:
            raise ValueError("taker v1 does not model partial-fill timeout; use zero")

    def book_age_seconds(self, book: CanonicalBook, decision_at: datetime | None = None) -> Decimal:
        now = decision_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("decision_at must be timezone-aware")
        return decimal((now - book.stamp.received_at).total_seconds())

    def is_fresh(self, book: CanonicalBook, decision_at: datetime | None = None) -> bool:
        self.validate()
        age = self.book_age_seconds(book, decision_at)
        return Decimal("0") <= age <= self.max_book_age_seconds

    @property
    def adverse_price_haircut(self) -> Decimal:
        self.validate()
        return self.latency_seconds * self.adverse_price_per_second

    def metadata(self, book: CanonicalBook, decision_at: datetime | None = None) -> dict[str, str]:
        return {
            "execution_model": "taker_latency_stress_v1",
            "book_age_seconds": str(self.book_age_seconds(book, decision_at)),
            "max_book_age_seconds": str(self.max_book_age_seconds),
            "latency_seconds": str(self.latency_seconds),
            "adverse_price_haircut": str(self.adverse_price_haircut),
            "maker_model": "not_modeled",
            "partial_fill_timeout_seconds": str(self.partial_fill_timeout_seconds),
        }
