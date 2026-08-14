"""Paper-study lifecycle economics; no pricing, signal, or order capability."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


@dataclass(frozen=True)
class LifecycleEconomics:
    lifecycle: str
    contracts: Decimal
    entry_total_debit: Decimal
    terminal_cashflow: Decimal
    net_pnl: Decimal
    locked_capital: Decimal
    return_on_locked_capital: Decimal
    holding_seconds: Decimal
    dollars_per_contract: Decimal


def _result(lifecycle: str, contracts: Decimal, entry_total_debit: Decimal,
            terminal_cashflow: Decimal, holding_seconds: Decimal) -> LifecycleEconomics:
    if contracts <= 0 or entry_total_debit <= 0 or holding_seconds < 0:
        raise ValueError("contracts, debit, and holding time must be valid")
    net = terminal_cashflow - entry_total_debit
    return LifecycleEconomics(
        lifecycle=lifecycle, contracts=contracts, entry_total_debit=entry_total_debit,
        terminal_cashflow=terminal_cashflow, net_pnl=net, locked_capital=entry_total_debit,
        return_on_locked_capital=net / entry_total_debit, holding_seconds=holding_seconds,
        dollars_per_contract=net / contracts,
    )


def entry_to_settlement(contracts: Decimal, entry_total_debit: Decimal,
                        won: bool, holding_seconds: Decimal) -> LifecycleEconomics:
    return _result("entry_to_settlement", contracts, entry_total_debit, contracts if won else Decimal("0"), holding_seconds)


def entry_to_exit(contracts: Decimal, entry_total_debit: Decimal, exit_proceeds_after_fees: Decimal,
                  holding_seconds: Decimal) -> LifecycleEconomics:
    if exit_proceeds_after_fees < 0:
        raise ValueError("exit proceeds cannot be negative")
    return _result("entry_to_exit", contracts, entry_total_debit, exit_proceeds_after_fees, holding_seconds)


def empirical_streak_summary(net_pnls: Iterable[Decimal], bankroll: Decimal) -> dict[str, Decimal | int]:
    """Deterministic historical stress summary, not a simulated risk guarantee."""
    if bankroll <= 0:
        raise ValueError("bankroll must be positive")
    longest = current = 0
    cumulative_loss = Decimal("0")
    worst_streak_loss = Decimal("0")
    for pnl in net_pnls:
        if pnl < 0:
            current += 1
            cumulative_loss += -pnl
            if current > longest:
                longest = current
            worst_streak_loss = max(worst_streak_loss, cumulative_loss)
        else:
            current = 0
            cumulative_loss = Decimal("0")
    return {
        "observed_longest_loss_streak": longest,
        "observed_worst_consecutive_loss_dollars": worst_streak_loss,
        "bankroll_after_observed_worst_streak": bankroll - worst_streak_loss,
    }
