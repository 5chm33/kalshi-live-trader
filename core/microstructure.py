"""Pregame MLB *displayed-book feasibility* math. Never treats a quote as a fill.

A paired YES purchase in two mutually exclusive winner markets pays exactly $1
only for ordinary binary settlement; fair-price and cancelled events are exceptions.
All marks below are hypothetical quotes, NOT executable realized profits.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING

from core.public_market import MarketDataError, quote_from_orderbook

MONEY = Decimal("1")
CENT = Decimal("0.01")
MICRO = Decimal("0.000001")
OFFSETS = {"EDT": -4, "EST": -5, "CDT": -5, "CST": -6,
           "MDT": -6, "MST": -7, "PDT": -7, "PST": -8}
SCHEDULE = re.compile(
    r"\boriginally scheduled for ([A-Z][a-z]{2} \d{1,2}, 20\d{2}) "
    r"at (\d{1,2}:\d{2} [AP]M) (EDT|EST|CDT|CST|MDT|MST|PDT|PST)\b"
)


def scheduled_start(markets: list[dict]) -> datetime:
    """Use the identical contract rule in both markets; occurrence is not start."""
    if len(markets) != 2 or len({m.get("ticker") for m in markets}) != 2:
        raise MarketDataError("Exactly two distinct winner markets required")
    starts = []
    for market in markets:
        text = market.get("rules_primary")
        if not isinstance(text, str):
            raise MarketDataError("Missing scheduled start in rules")
        hits = SCHEDULE.findall(text)
        if len(hits) != 1:
            raise MarketDataError("Ambiguous or missing original scheduled start")
        day, clock, tz = hits[0]
        local = datetime.strptime(f"{day} {clock}", "%b %d, %Y %I:%M %p")
        starts.append(local.replace(tzinfo=timezone(timedelta(hours=OFFSETS[tz]))).astimezone(timezone.utc))
    if starts[0] != starts[1]:
        raise MarketDataError("Winner markets disagree on scheduled start")
    return starts[0]


def effective_fees(series: dict, event: dict) -> tuple[str, Decimal]:
    if event.get("series_ticker") != series.get("ticker") or not series.get("ticker"):
        raise MarketDataError("Event/series mismatch")
    typ = event.get("fee_type_override") or series.get("fee_type")
    multiplier = event.get("fee_multiplier_override")
    if multiplier is None:
        multiplier = series.get("fee_multiplier")
    try:
        m = Decimal(str(multiplier))
    except (TypeError, ValueError):
        raise MarketDataError("Fee multiplier unavailable")
    if not m.is_finite() or m < 0 or m > 10 or typ not in ("quadratic", "quadratic_with_maker_fees"):
        raise MarketDataError("Unrecognized fee type or multiplier")
    return typ, m


def _grid_check(price: Decimal, market: dict) -> None:
    ranges = market.get("price_ranges")
    if not isinstance(ranges, list) or not ranges:
        raise MarketDataError("Missing market price grid")
    for span in ranges:
        try:
            lo, hi, step = (Decimal(str(span[k])) for k in ("start", "end", "step"))
        except (KeyError, ValueError, TypeError, ArithmeticError):
            raise MarketDataError("Malformed market price grid")
        if all(x.is_finite() for x in (lo, hi, step)) and 0 <= lo <= price <= hi <= 1 and step > 0:
            if (price - lo) % step == 0:
                return
    raise MarketDataError("Best bid is off the current price grid")


def fee_estimate(price: Decimal, fee_type: str, multiplier: Decimal, *, maker: bool) -> Decimal:
    if not isinstance(price, Decimal) or not price.is_finite() or not 0 < price < 1:
        raise MarketDataError("Invalid price for fee estimate")
    if fee_type not in ("quadratic", "quadratic_with_maker_fees"):
        raise MarketDataError("Unknown fee type")
    if not isinstance(multiplier, Decimal) or not multiplier.is_finite() or not 0 <= multiplier <= 10:
        raise MarketDataError("Unknown multiplier")
    base = Decimal("0.0175") if maker else Decimal("0.07")
    # A resting order without maker fees still incurs price-alignment rounding
    # when a sub-cent buy finally fills. No future accumulator rebate assumed.
    raw = (Decimal("0") if maker and fee_type == "quadratic" else
           (base * multiplier * price * (MONEY - price)).quantize(MICRO, rounding=ROUND_CEILING))
    # Kalshi floors signed buyer revenue minus model fee onto the non-direct
    # account's cent grid. This is ceil(price + fee), not ceil(fee) alone.
    debit = (price + raw).quantize(CENT, rounding=ROUND_CEILING)
    return debit - price


def paired_book(markets: list[dict], books: list[dict], series: dict, event: dict) -> dict:
    """Two independently displayed YES bids; no queue/fill assumption."""
    if len(markets) != 2 or len(books) != 2 or not event.get("mutually_exclusive"):
        raise MarketDataError("Two mutually exclusive winner markets required")
    if any(m.get("status") != "active" or m.get("event_ticker") != event.get("event_ticker")
           or not m.get("rules_primary") for m in markets):
        raise MarketDataError("Inactive, unmatched, or ruleless winner market")
    if any(m.get("is_provisional") is True for m in markets):
        raise MarketDataError("Provisional market")
    scheduled_start(markets)
    typ, multiplier = effective_fees(series, event)
    quotes = [quote_from_orderbook(b) for b in books]
    if any(q is None for q in quotes):
        return {"eligible": False, "reason": "one_sided_or_empty"}
    bids = []
    sizes = []
    for market, book, quote in zip(markets, books, quotes):
        price = quote.yes_bid
        _grid_check(price, market)
        _grid_check(quote.no_bid, market)
        levels = book["yes_dollars"]
        best = max((Decimal(str(row[0])), Decimal(str(row[1]))) for row in levels
                   if isinstance(row, list) and len(row) >= 2 and Decimal(str(row[0])) == price)
        bids.append(price)
        sizes.append(best[1])
    if any(size < 1 for size in sizes):
        return {"eligible": False, "reason": "insufficient_yes_bid_depth"}
    spread = MONEY - sum(bids)
    fees = sum((fee_estimate(b, typ, multiplier, maker=True) for b in bids), Decimal("0"))
    # This conditional paired mark assumes *both* resting YES bids fill and an
    # ordinary one-winner binary settlement. Never present it as achieved P&L.
    return {"eligible": True, "yes_bids_dollars": [str(b) for b in bids],
            "yes_bid_sizes_fp": [str(n) for n in sizes], "conditional_gross_spread_dollars": str(spread),
            "fee_type": typ, "fee_multiplier": str(multiplier),
            "conservative_non_direct_maker_fee_dollars": str(fees),
            "conditional_paired_mark_dollars": str(spread - fees),
            "not_a_fill": True}
