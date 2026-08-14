"""Fee- and depth-aware expected-value assessment for V11 paper fills."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from research.models import PaperFill, StrategySignal


@dataclass(frozen=True)
class ExpectedValue:
    filled_contracts: Decimal
    conservative_win_probability: Decimal
    expected_settlement_payout: Decimal
    total_debit: Decimal
    expected_net_pnl: Decimal
    expected_net_per_contract: Decimal
    eligible: bool
    reason: str


def assess(signal: StrategySignal, fill: PaperFill | None, min_net_per_contract: Decimal = Decimal("0.02")) -> ExpectedValue:
    """Assess only an executable paper fill, never a displayed midpoint.

    `conservative_probability` is the predicted YES settlement probability. The
    reciprocal is used for a NO position. A no-fill or partial displayed-book
    fill cannot be treated as an executable full-size opportunity.
    """
    if min_net_per_contract <= 0:
        raise ValueError("min_net_per_contract must be positive")
    if fill is None or fill.filled_contracts <= 0:
        return ExpectedValue(Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), False, "no_executable_displayed_depth")
    win_probability = signal.conservative_probability if signal.outcome_side == "yes" else Decimal("1") - signal.conservative_probability
    if not (Decimal("0") <= win_probability <= Decimal("1")):
        raise ValueError("conservative probability must be within [0, 1]")
    payout = win_probability * fill.filled_contracts
    net = payout - fill.total_debit
    per_contract = net / fill.filled_contracts
    eligible = per_contract >= min_net_per_contract
    reason = "fee_depth_adjusted_ev_pass" if eligible else "fee_depth_adjusted_ev_below_threshold"
    return ExpectedValue(fill.filled_contracts, win_probability, payout, fill.total_debit, net, per_contract, eligible, reason)
