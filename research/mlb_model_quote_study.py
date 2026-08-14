"""Out-of-sample empirical MLB probability versus archived Kalshi quote study.

This study selects at most one pre-specified late-lead state per game/contract,
uses a model trained strictly before the test window, and accounts for the
published taker-fee formula. It remains non-executable because historical
candles do not provide depth, queue position, or fill confirmation.
"""
from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from research.fees import conservative_rounding_reserve, estimate_fee
from research.mlb_calibration import EmpiricalMLBModel


def evaluate_model_vs_quotes(
    database: str | Path,
    training_end: str,
    test_start: str,
    test_end: str,
    minimum_games: int = 100,
    minimum_expected_net_per_contract: Decimal = Decimal("0.02"),
) -> dict[str, Any]:
    if test_start <= training_end or test_end < test_start:
        raise ValueError("test period must begin after the training cutoff")
    if minimum_expected_net_per_contract <= 0:
        raise ValueError("minimum expected net per contract must be positive")
    model = EmpiricalMLBModel.fit(database, training_end, minimum_games)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """WITH first_quote AS (
               SELECT q.*, s.game_date, s.inning, s.inning_half, s.leader_is_home, s.lead_runs,
                      m.raw_json AS market_raw,
                      ROW_NUMBER() OVER (PARTITION BY q.game_pk, q.ticker ORDER BY q.state_source_at) AS rn
               FROM mlb_quote_study q
               JOIN mlb_historical_states s
                 ON s.game_pk = q.game_pk AND s.at_bat_index = q.at_bat_index
               JOIN kalshi_historical_markets m ON m.ticker = q.ticker
               WHERE s.game_date >= ? AND s.game_date <= ? AND q.yes_ask_close IS NOT NULL
             ) SELECT * FROM first_quote WHERE rn = 1""",
        (test_start, test_end),
    ).fetchall()
    candidates = 0
    missing_probability = 0
    skipped_multiplier = 0
    expected_values: list[Decimal] = []
    realized_values: list[Decimal] = []
    wins = 0
    for row in rows:
        probability_float = model.probability(
            row["inning"], row["inning_half"], bool(row["leader_is_home"]), row["lead_runs"]
        )
        if probability_float is None:
            missing_probability += 1
            continue
        raw = json.loads(row["market_raw"])
        multiplier = raw.get("notional_value_dollars")
        if multiplier is None:
            skipped_multiplier += 1
            continue
        ask = Decimal(str(row["yes_ask_close"]))
        if not (Decimal("0") < ask < Decimal("1")):
            continue
        probability = Decimal(str(probability_float))
        fee = estimate_fee(ask, Decimal("1"), Decimal(str(multiplier)), "taker")
        reserve = conservative_rounding_reserve(Decimal("1"))
        expected = probability - ask - fee - reserve
        if expected < minimum_expected_net_per_contract:
            continue
        candidates += 1
        expected_values.append(expected)
        realized = (Decimal("1") if int(row["leader_won"]) else Decimal("0")) - ask - fee - reserve
        realized_values.append(realized)
        wins += int(row["leader_won"])
    if not candidates:
        return {
            "status": "no_eligible_model_quote_candidates",
            "aligned_first_states": len(rows), "missing_calibrated_probability": missing_probability,
            "skipped_missing_multiplier": skipped_multiplier,
            "training_end": training_end, "test_start": test_start, "test_end": test_end,
            "execution_claim": "none; archived candles do not prove fillable depth",
        }
    return {
        "status": "out_of_sample_quote_only_not_execution_proof",
        "training_end": training_end, "test_start": test_start, "test_end": test_end,
        "minimum_games": minimum_games,
        "minimum_expected_net_per_contract": str(minimum_expected_net_per_contract),
        "aligned_first_states": len(rows), "missing_calibrated_probability": missing_probability,
        "skipped_missing_multiplier": skipped_multiplier,
        "selected_quote_proxy_candidates": candidates,
        "total_expected_net_per_contract_proxy": str(sum(expected_values)),
        "mean_expected_net_per_contract_proxy": str(sum(expected_values) / candidates),
        "total_realized_net_per_contract_proxy": str(sum(realized_values)),
        "mean_realized_net_per_contract_proxy": str(sum(realized_values) / candidates),
        "realized_leader_win_rate": wins / candidates,
        "excludes": [
            "displayed depth", "partial fills", "queue position", "adverse selection",
            "market-data latency", "order acknowledgement latency", "actual exchange fill fees",
        ],
        "execution_claim": "none; archived candles do not prove fillable depth",
    }
