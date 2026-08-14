"""Readiness gates: research evidence and production safety are intentionally independent.

No return value from this module enables an order. A research pass only names a
review candidate; a production pass only names a separate production review
candidate. Human approval and a separately reviewed execution system would still
be required outside V11.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping


@dataclass(frozen=True)
class ResearchEvidence:
    manifest_pinned: bool
    stopping_rule_met: bool
    prospective_lifecycle_complete: bool
    calibration_passed: bool
    placebo_passed: bool
    liquidity_passed: bool
    latency_sensitivity_passed: bool
    out_of_sample_lcb_positive: bool
    independent_reproduction_complete: bool


@dataclass(frozen=True)
class ProductionControls:
    credential_isolation_tested: bool
    reconciliation_tested: bool
    kill_switch_tested: bool
    exchange_status_handling_tested: bool
    idempotency_tested: bool
    cancel_sell_path_tested: bool
    durable_audit_tested: bool
    alert_destination_tested: bool
    incident_runbook_reviewed: bool
    human_oversight_assigned: bool


def _failures(values: Mapping[str, bool]) -> list[str]:
    return [name for name, passed in values.items() if not passed]


def research_gate(evidence: ResearchEvidence) -> dict[str, object]:
    failures = _failures(asdict(evidence))
    return {
        "stage": "research_readiness",
        "eligible": not failures,
        "outcome": "review_candidate" if not failures else "continue_or_retire_per_manifest",
        "failures": failures,
        "live_orders_enabled": False,
        "next_gate": "independent_model_review",
    }


def production_gate(controls: ProductionControls, research_review_accepted: bool) -> dict[str, object]:
    failures = _failures(asdict(controls))
    if not research_review_accepted:
        failures.insert(0, "independent_research_review_not_accepted")
    return {
        "stage": "production_readiness",
        "eligible": not failures,
        "outcome": "production_review_candidate" if not failures else "production_not_ready",
        "failures": failures,
        "live_orders_enabled": False,
        "human_approval_required": True,
        "required_future_action": "explicit_transaction_specific_user_confirmation_and_separately_reviewed_execution_system",
    }
