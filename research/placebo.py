"""Paired placebo analysis for detecting spurious paper-study results."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable


def paired_placebo_report(treatment_net: Iterable[Decimal], placebo_net: Iterable[Decimal], label: str) -> dict[str, object]:
    treatment = list(treatment_net)
    placebo = list(placebo_net)
    if len(treatment) != len(placebo):
        raise ValueError("treatment and placebo series must be paired")
    if not treatment:
        return {"label": label, "status": "insufficient_data", "executable": False}
    treatment_mean = sum(treatment, Decimal("0")) / len(treatment)
    placebo_mean = sum(placebo, Decimal("0")) / len(placebo)
    difference = treatment_mean - placebo_mean
    return {
        "label": label,
        "status": "exploratory_control_only",
        "executable": False,
        "observations": len(treatment),
        "treatment_mean_net": str(treatment_mean),
        "placebo_mean_net": str(placebo_mean),
        "paired_difference": str(difference),
        "interpretation": "A control result cannot promote a strategy; it can only challenge an apparent treatment effect.",
    }
