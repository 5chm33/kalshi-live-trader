"""Pure, testable Kalshi V2 price and risk math; no network or orders.

All V2 prices are YES-book prices. A buy-NO order is an ask (sell YES) at
1 - the NO price, and a sell-NO order is a bid (buy YES) at 1 - NO price.
Neither a signal nor a valid order plan establishes profitable execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR

from core.public_market import BookQuote, decimal_price

CENT = Decimal("0.01")
ONE = Decimal("1")


@dataclass(frozen=True)
class V2OrderPlan:
    outcome: str
    action: str
    side: str
    outcome_limit: Decimal
    yes_limit: Decimal
    count: int

    def payload(self, ticker: str, client_order_id: str, *, reduce_only: bool = False) -> dict:
        if not ticker or not client_order_id or len(client_order_id) > 64:
            raise ValueError("Missing ticker or valid client order ID")
        if reduce_only != (self.action == "sell"):
            raise ValueError("Sell exits must be reduce-only; entries must not")
        return {"ticker": ticker, "client_order_id": client_order_id,
                "side": self.side, "count": f"{self.count:.2f}",
                "price": f"{self.yes_limit:.4f}",
                "time_in_force": "immediate_or_cancel",
                "self_trade_prevention_type": "taker_at_cross",
                "post_only": False, "cancel_order_on_pause": True,
                "reduce_only": reduce_only, "subaccount": 0, "exchange_index": -1}


def plan(outcome: str, action: str, count: int, outcome_limit: Decimal) -> V2OrderPlan:
    if outcome not in {"yes", "no"} or action not in {"buy", "sell"}:
        raise ValueError("Outcome must be yes/no and action buy/sell")
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise ValueError("Pilot plan requires 1–10 whole contracts")
    price = decimal_price(outcome_limit)
    if price != price.quantize(Decimal("0.0001")):
        raise ValueError("Off-grid price")
    yes_price = price if outcome == "yes" else ONE - price
    side = "bid" if (outcome == "yes") == (action == "buy") else "ask"
    return V2OrderPlan(outcome, action, side, price, yes_price, count)


def executable_price(quote: BookQuote, outcome: str, action: str) -> tuple[Decimal, Decimal]:
    """Return top-of-book outcome price and available quantity, never a fake ask."""
    if action not in {"buy", "sell"}:
        raise ValueError("unknown action")
    if outcome == "yes":
        return ((quote.yes_ask, quote.yes_ask_size) if action == "buy"
                else (quote.yes_bid, quote.no_ask_size))
    if outcome == "no":
        return ((quote.no_ask, quote.no_ask_size) if action == "buy"
                else (quote.no_bid, quote.yes_ask_size))
    raise ValueError("unknown outcome")


def pilot_size(*, available_cash: Decimal, existing_exposure: Decimal,
               pending_commitments: Decimal, price: Decimal, fee_reserve: Decimal,
               ask_size: Decimal, calibrated_net_edge: Decimal | None,
               absolute_cap: Decimal = Decimal("10.00"),
               per_order_cap: Decimal = Decimal("0.50")) -> int:
    """One-contract-or-zero sizing with a verified positive net edge.

    This is a *necessary* arithmetic gate, never permission to place an order.
    Invalid/missing inputs raise, negative or unvalidated edges return zero.
    Caps include open exposure and all pending commitments. Fee reserve is
    conservative and depends on the actual market's fee schedule.
    """
    values = [available_cash, existing_exposure, pending_commitments,
              price, fee_reserve, ask_size, absolute_cap, per_order_cap]
    if any(not isinstance(x, Decimal) or not x.is_finite() for x in values):
        raise ValueError("Risk inputs must be finite Decimal values")
    if any(x < 0 for x in values) or not (0 < price < 1):
        raise ValueError("Invalid collateral, quote, or depth")
    if ask_size < 1:
        return 0
    if calibrated_net_edge is None:
        return 0
    if not isinstance(calibrated_net_edge, Decimal) or not calibrated_net_edge.is_finite():
        raise ValueError("Invalid edge")
    if calibrated_net_edge <= 0:
        return 0
    maximum = min(available_cash - pending_commitments,
                  absolute_cap - existing_exposure - pending_commitments,
                  per_order_cap)
    contract_cost = price + fee_reserve
    if maximum < contract_cost:
        return 0
    return min(1, int((maximum / contract_cost).to_integral_value(rounding=ROUND_FLOOR)),
               int(ask_size.to_integral_value(rounding=ROUND_FLOOR)))
