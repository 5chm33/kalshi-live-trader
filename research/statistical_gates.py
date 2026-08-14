"""Transparent inference gates for paper-research promotion decisions.

These helpers evaluate observed data only. They do not create a trading signal.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import NormalDist
from typing import Iterable

from research.models import decimal


@dataclass(frozen=True)
class GatePolicy:
    minimum_independent_clusters: int
    maximum_variants: int
    maximum_calibration_error: Decimal
    minimum_lcb_net_per_contract: Decimal
    one_sided_alpha: Decimal = Decimal("0.05")

    def validate(self) -> None:
        if self.minimum_independent_clusters < 1 or self.maximum_variants < 1:
            raise ValueError("minimum clusters and maximum variants must be positive")
        if not (Decimal("0") < self.one_sided_alpha < Decimal("1")):
            raise ValueError("one-sided alpha must be between zero and one")


def one_sided_wilson_lower(successes: int, trials: int, alpha: Decimal = Decimal("0.05")) -> Decimal | None:
    """Wilson lower bound for a Bernoulli rate; returns None for no observations."""
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("invalid Bernoulli counts")
    if trials == 0:
        return None
    z = Decimal(str(NormalDist().inv_cdf(float(Decimal("1") - alpha))))
    n = Decimal(trials)
    p = Decimal(successes) / n
    numerator = p + z * z / (Decimal("2") * n) - z * ((p * (Decimal("1") - p) / n + z * z / (Decimal("4") * n * n)).sqrt())
    denominator = Decimal("1") + z * z / n
    return numerator / denominator


def calibration_error(probabilities: Iterable[Decimal | str], outcomes: Iterable[int], bins: int = 10) -> Decimal | None:
    """Equal-width expected calibration error over observed probabilities."""
    pairs = [(decimal(p), int(y)) for p, y in zip(probabilities, outcomes)]
    if not pairs:
        return None
    if bins < 1:
        raise ValueError("bins must be positive")
    total = Decimal(len(pairs))
    error = Decimal("0")
    for index in range(bins):
        low, high = Decimal(index) / bins, Decimal(index + 1) / bins
        bucket = [(p, y) for p, y in pairs if (low <= p < high) or (index == bins - 1 and p == high)]
        if not bucket:
            continue
        mean_probability = sum((p for p, _ in bucket), Decimal("0")) / len(bucket)
        mean_outcome = Decimal(sum(y for _, y in bucket)) / len(bucket)
        error += Decimal(len(bucket)) / total * abs(mean_probability - mean_outcome)
    return error


def promotion_gate(policy: GatePolicy, independent_clusters: int, observed_calibration_error: Decimal | None,
                   lcb_net_per_contract: Decimal | None, registered_variants_used: int) -> dict[str, object]:
    """Return all gate failures rather than a binary claim of profitability."""
    policy.validate()
    failures: list[str] = []
    if independent_clusters < policy.minimum_independent_clusters:
        failures.append("insufficient_independent_clusters")
    if observed_calibration_error is None or observed_calibration_error > policy.maximum_calibration_error:
        failures.append("calibration_gate_failed")
    if lcb_net_per_contract is None or lcb_net_per_contract <= policy.minimum_lcb_net_per_contract:
        failures.append("net_lcb_not_positive")
    if registered_variants_used > policy.maximum_variants:
        failures.append("multiple_testing_budget_exceeded")
    return {"eligible": not failures, "failures": failures, "independent_clusters": independent_clusters,
            "calibration_error": str(observed_calibration_error) if observed_calibration_error is not None else None,
            "lcb_net_per_contract": str(lcb_net_per_contract) if lcb_net_per_contract is not None else None,
            "registered_variants_used": registered_variants_used}
