"""Immutable archive for retired hypotheses; never use it to create a signal."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from research.audit import sha256


@dataclass(frozen=True)
class NegativeResult:
    strategy_family: str
    strategy_version: str
    hypothesis: str
    specification_sha256: str
    manifest_id: str | None
    eligible_sample: Mapping[str, Any]
    exclusions: Mapping[str, Any]
    uncertainty_interval: Mapping[str, Any]
    primary_outcome: Mapping[str, Any]
    retirement_reason: str
    retired_at: str
    code_commit: str
    previous_result_sha256: str | None = None

    @property
    def payload(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def result_sha256(self) -> str:
        return sha256(self.payload)

    def validate(self) -> None:
        if not self.strategy_family or not self.strategy_version or not self.hypothesis:
            raise ValueError("strategy identity and hypothesis are required")
        if len(self.specification_sha256) < 16 or len(self.code_commit) < 7:
            raise ValueError("frozen specification and code commit are required")
        if not self.retirement_reason or not self.retired_at:
            raise ValueError("retirement reason and timestamp are required")
        datetime.fromisoformat(self.retired_at.replace("Z", "+00:00"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
