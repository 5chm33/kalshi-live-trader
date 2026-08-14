"""Evaluate pre-specified late-lead states against archived Kalshi quote candles.

This is a quote-only retrospective study. Candles do not contain displayed depth
or fill acknowledgements, so its results cannot be represented as executable
P&L or evidence for live deployment.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from research.fees import conservative_rounding_reserve, estimate_fee


def evaluate_quote_study(database: str | Path) -> dict[str, Any]:
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT q.*, m.raw_json AS market_raw
           FROM mlb_quote_study q
           JOIN kalshi_historical_markets m ON m.ticker = q.ticker
           WHERE q.yes_ask_close IS NOT NULL"""
    ).fetchall()
    net_values: list[Decimal] = []
    delays: list[float] = []
    winners = 0
    skipped_missing_multiplier = 0
    for row in rows:
        raw = json.loads(row["market_raw"])
        multiplier = raw.get("notional_value_dollars")
        if multiplier is None:
            skipped_missing_multiplier += 1
            continue
        price = Decimal(str(row["yes_ask_close"]))
        if not (Decimal("0") < price < Decimal("1")):
            continue
        fee = estimate_fee(price, Decimal("1"), Decimal(str(multiplier)), "taker")
        reserve = conservative_rounding_reserve(Decimal("1"))
        payout = Decimal("1") if int(row["leader_won"]) else Decimal("0")
        net_values.append(payout - price - fee - reserve)
        delays.append(float(row["quote_delay_seconds"]))
        winners += int(row["leader_won"])
    if not net_values:
        return {
            "status": "insufficient_aligned_quote_rows",
            "aligned_rows": 0,
            "skipped_missing_multiplier": skipped_missing_multiplier,
            "execution_claim": "none; historical candles do not prove fillable depth",
        }
    positive = sum(value > 0 for value in net_values)
    return {
        "status": "quote_only_retrospective_not_execution_proof",
        "aligned_rows": len(net_values),
        "skipped_missing_multiplier": skipped_missing_multiplier,
        "leader_win_rate": winners / len(net_values),
        "mean_quote_delay_seconds": sum(delays) / len(delays),
        "total_fee_adjusted_quote_proxy_pnl_per_contract": str(sum(net_values)),
        "mean_fee_adjusted_quote_proxy_pnl_per_contract": str(sum(net_values) / len(net_values)),
        "fraction_positive_realized_outcomes": positive / len(net_values),
        "excludes": [
            "displayed depth", "partial fills", "queue position", "adverse selection",
            "market-data latency", "order acknowledgement latency", "actual exchange fees",
        ],
        "execution_claim": "none; historical candles do not prove fillable depth",
    }
