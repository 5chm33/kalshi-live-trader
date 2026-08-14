"""Exploratory segmentation of the historical MLB/Kalshi quote-only study.

This report is a hypothesis generator. Any bucket appearing favorable here must
be locked and evaluated on a chronologically later, unused holdout window before
it may become a paper-trading candidate.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from research.fees import conservative_rounding_reserve, estimate_fee


def _bucket(inning: int, lead: int, leader_is_home: bool) -> str:
    inning_group = "9+" if inning >= 9 else str(inning)
    lead_group = "5+" if lead >= 5 else str(lead)
    venue = "home" if leader_is_home else "away"
    return f"inning={inning_group}|lead={lead_group}|leader={venue}"


def explore(database: str | Path, minimum_rows: int = 25) -> dict[str, Any]:
    if minimum_rows <= 0:
        raise ValueError("minimum_rows must be positive")
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """WITH first_quote AS (
               SELECT q.*, s.inning, s.lead_runs, s.leader_is_home, m.raw_json AS market_raw,
                      ROW_NUMBER() OVER (PARTITION BY q.game_pk, q.ticker ORDER BY q.state_source_at) AS rn
               FROM mlb_quote_study q
               JOIN mlb_historical_states s ON s.game_pk=q.game_pk AND s.at_bat_index=q.at_bat_index
               JOIN kalshi_historical_markets m ON m.ticker=q.ticker
             ) SELECT * FROM first_quote WHERE rn=1 AND yes_ask_close IS NOT NULL"""
    ).fetchall()
    groups: dict[str, list[tuple[Decimal, bool, Decimal]]] = defaultdict(list)
    skipped = 0
    for row in rows:
        raw = json.loads(row["market_raw"])
        multiplier = raw.get("notional_value_dollars")
        if multiplier is None:
            skipped += 1
            continue
        ask = Decimal(str(row["yes_ask_close"]))
        if not (Decimal("0") < ask < Decimal("1")):
            continue
        fee = estimate_fee(ask, Decimal("1"), Decimal(str(multiplier)), "taker")
        net = (Decimal("1") if int(row["leader_won"]) else Decimal("0")) - ask - fee - conservative_rounding_reserve(Decimal("1"))
        groups[_bucket(int(row["inning"]), int(row["lead_runs"]), bool(row["leader_is_home"]))].append(
            (net, bool(row["leader_won"]), ask)
        )
    report = []
    for key, values in groups.items():
        if len(values) < minimum_rows:
            continue
        net = sum(item[0] for item in values)
        wins = sum(item[1] for item in values)
        asks = sum(item[2] for item in values)
        report.append({
            "bucket": key, "rows": len(values), "leader_win_rate": wins / len(values),
            "mean_ask": str(asks / len(values)),
            "mean_fee_adjusted_quote_proxy_pnl": str(net / len(values)),
            "total_fee_adjusted_quote_proxy_pnl": str(net),
            "status": "exploratory_requires_unseen_holdout_validation",
        })
    report.sort(key=lambda row: Decimal(row["mean_fee_adjusted_quote_proxy_pnl"]), reverse=True)
    return {
        "status": "exploratory_only_not_a_strategy",
        "first_state_per_game_contract": True,
        "minimum_rows": minimum_rows,
        "eligible_buckets": report,
        "skipped_missing_multiplier": skipped,
        "execution_claim": "none; historical candles do not prove fillable depth",
    }
