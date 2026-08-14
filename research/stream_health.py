"""Paper-data stream health metrics; contains no market or order behavior."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class StreamHealth:
    connects: int = 0
    reconnects: int = 0
    errors: int = 0
    sequence_gaps: int = 0
    resyncs: int = 0
    messages: int = 0
    max_source_to_receipt_ms: Decimal = Decimal("0")

    def connected(self) -> None:
        self.connects += 1
        if self.connects > 1:
            self.reconnects += 1

    def errored(self) -> None:
        self.errors += 1

    def gap(self) -> None:
        self.sequence_gaps += 1

    def resynced(self) -> None:
        self.resyncs += 1

    def message(self, source_at: datetime | None, received_at: datetime) -> None:
        self.messages += 1
        if source_at is None:
            return
        delay = Decimal(str((received_at - source_at).total_seconds() * 1000))
        self.max_source_to_receipt_ms = max(self.max_source_to_receipt_ms, delay)

    def payload(self) -> dict[str, int | str]:
        return {
            "connects": self.connects,
            "reconnects": self.reconnects,
            "errors": self.errors,
            "sequence_gaps": self.sequence_gaps,
            "resyncs": self.resyncs,
            "messages": self.messages,
            "max_source_to_receipt_ms": str(self.max_source_to_receipt_ms),
        }
