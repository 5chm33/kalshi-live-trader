"""Fixed stopping rules for prospective research manifests."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True)
class StoppingRule:
    prospective_start_at: datetime
    prospective_end_at: datetime
    maximum_eligible_candidates: int
    minimum_settled_candidates: int

    @classmethod
    def from_manifest(cls, payload: Mapping[str, Any]) -> "StoppingRule":
        window = payload.get("collection_window")
        if not isinstance(window, Mapping):
            universe = payload.get("market_universe")
            protocol = universe.get("research_protocol") if isinstance(universe, Mapping) else None
            window = protocol.get("collection_window") if isinstance(protocol, Mapping) else None
        if not isinstance(window, Mapping):
            raise ValueError("manifest has no fixed collection_window")
        try:
            start = datetime.fromisoformat(str(window["prospective_start_at"]))
            end = datetime.fromisoformat(str(window["prospective_end_at"]))
            maximum = int(window["maximum_eligible_candidates"])
            minimum = int(window["minimum_settled_candidates"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("manifest collection_window is incomplete") from exc
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("manifest prospective time window is invalid")
        if maximum < 1 or minimum < 1 or minimum > maximum:
            raise ValueError("manifest sample budget is invalid")
        return cls(start, end, maximum, minimum)


def collection_status(rule: StoppingRule, eligible_candidates: int, settled_candidates: int,
                      now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    if now < rule.prospective_start_at:
        return {"status": "not_started", "collect": False, "reason": "before_registered_window"}
    if eligible_candidates >= rule.maximum_eligible_candidates:
        return {"status": "stopped", "collect": False, "reason": "eligible_candidate_budget_reached"}
    if now >= rule.prospective_end_at:
        return {"status": "stopped", "collect": False, "reason": "registered_end_time_reached",
                "retire_or_respecify": settled_candidates < rule.minimum_settled_candidates}
    return {"status": "collecting", "collect": True, "reason": "within_registered_window",
            "eligible_candidates": eligible_candidates, "settled_candidates": settled_candidates}
