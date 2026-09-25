"""Fill-based accounting with an explicit, freshness-limited public bid mark.

For a held outcome, entry costs and exit proceeds use that outcome's price,
not V2's YES-only price for NO. Exchange fill fees are actual amounts from the
fill records. Unrealized liquidation assumes one top-of-book exit, subject to
available depth and an estimated future fee; it is NOT guaranteed P&L.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from account_preflight import strict_decimal
from core.public_market import BookQuote


@dataclass(frozen=True)
class PositionValue:
    outcome: str
    remaining_count: Decimal
    entry_cost_total: Decimal
    actual_exit_proceeds: Decimal
    realized_pnl: Decimal
    conservative_bid: Decimal
    estimated_unrealized_pnl: Decimal
    estimated_total_pnl: Decimal
    observed_at: datetime


def value_position(*, outcome: str, entry_fills: list[dict], exit_fills: list[dict],
                   quote: BookQuote, observed_at: datetime, now: datetime,
                   estimated_exit_fee: Decimal) -> PositionValue:
    if outcome not in {"yes", "no"}:
        raise ValueError("Unknown outcome")
    if observed_at.tzinfo is None or now.tzinfo is None or not 0 <= (now-observed_at).total_seconds() <= 2:
        raise ValueError("Quote is absent, in the future, or more than 2 seconds old")
    if not entry_fills:
        raise ValueError("No confirmed entry fill")
    if not estimated_exit_fee.is_finite() or estimated_exit_fee < 0:
        raise ValueError("Missing or invalid future fee reserve")

    def summarize(fills: list[dict]) -> tuple[Decimal, Decimal, Decimal]:
        total_qty = total_price = total_fees = Decimal(0)
        ids = set()
        for fill in fills:
            fill_id = fill.get("fill_id")
            if not fill_id or fill_id in ids:
                raise ValueError("Missing or duplicate fill ID")
            ids.add(fill_id)
            qty = strict_decimal(fill.get("count_fp"), "count_fp")
            yes_price = strict_decimal(fill.get("yes_price_dollars"), "yes_price_dollars")
            fee = strict_decimal(fill.get("fee_cost"), "fee_cost")
            if qty <= 0 or not 0 < yes_price < 1 or fee < 0:
                raise ValueError("Invalid fill count, price, or fee")
            total_qty += qty
            total_price += qty * (yes_price if outcome == "yes" else Decimal(1) - yes_price)
            total_fees += fee
        return total_qty, total_price, total_fees

    bought, price_paid, entry_fees = summarize(entry_fills)
    sold, proceeds, exit_fees = summarize(exit_fills)
    if sold > bought:
        raise ValueError("Confirmed exits exceed held inventory")
    if {x.get("fill_id") for x in entry_fills} & {x.get("fill_id") for x in exit_fills}:
        raise ValueError("Same exchange fill counted twice")
    remaining = bought - sold
    bid = quote.yes_bid if outcome == "yes" else quote.no_bid
    depth = quote.no_ask_size if outcome == "yes" else quote.yes_ask_size
    if not bid.is_finite() or not 0 < bid < 1 or depth < remaining:
        raise ValueError("Insufficient executable depth for a full exit")
    if any(not value.is_finite() for value in (bought, price_paid, entry_fees, proceeds, exit_fees)):
        raise ValueError("Non-finite fill accounting")
    avg_entry_with_fee = (price_paid + entry_fees) / bought
    realized = proceeds - exit_fees - avg_entry_with_fee * sold
    unrealized = remaining * (bid - avg_entry_with_fee) - (estimated_exit_fee if remaining > 0 else 0)
    return PositionValue(outcome, remaining, price_paid + entry_fees,
                         proceeds - exit_fees, realized, bid, unrealized,
                         realized + unrealized, observed_at)


def exit_reason(value: PositionValue, *, entered_at: datetime, now: datetime,
                net_profit_target: Decimal = Decimal("0.02"),
                net_stop_loss: Decimal = Decimal("-0.05"),
                max_hold_seconds: int = 300) -> str | None:
    """Signal only; actual IOC exit requires a separate, verified reduce-only gate.

    A stop is not guaranteed: bid depth may vanish before an order can fill.
    """
    if entered_at.tzinfo is None or now.tzinfo is None or now < entered_at:
        raise ValueError("Invalid entry time")
    if value.remaining_count <= 0:
        return None
    if value.estimated_unrealized_pnl >= net_profit_target:
        return "profit_target"
    if value.estimated_unrealized_pnl <= net_stop_loss:
        return "loss_cut_request"
    if (now - entered_at).total_seconds() >= max_hold_seconds:
        return "time_exit_request"
    return None
