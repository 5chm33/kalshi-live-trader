"""Out-of-sample accuracy evaluation for the empirical MLB late-lead study.

This report measures probability quality only. It does not infer Kalshi trading
profitability because historical executable Kalshi quotes are a separate data
requirement.
"""
from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from research.mlb_calibration import EmpiricalMLBModel, _key


def evaluate_out_of_sample(
    database: str | Path,
    training_end: str,
    test_start: str,
    test_end: str,
    minimum_games: int = 100,
) -> dict[str, Any]:
    if not (test_start > training_end and test_end >= test_start):
        raise ValueError("test period must begin after training_end")
    model = EmpiricalMLBModel.fit(database, training_end, minimum_games)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """WITH ranked AS (
               SELECT *, ROW_NUMBER() OVER (
                 PARTITION BY game_pk, inning, inning_half, leader_is_home,
                              CASE WHEN lead_runs > 5 THEN 5 ELSE lead_runs END
                 ORDER BY at_bat_index
               ) AS rn
               FROM mlb_historical_states
               WHERE game_date >= ? AND game_date <= ?
             ) SELECT * FROM ranked WHERE rn = 1""",
        (test_start, test_end),
    ).fetchall()
    predictions: list[tuple[float, int, str]] = []
    skipped: dict[str, int] = defaultdict(int)
    for row in rows:
        key = _key(row["inning"], row["inning_half"], bool(row["leader_is_home"]), row["lead_runs"])
        probability = model.probability(row["inning"], row["inning_half"], bool(row["leader_is_home"]), row["lead_runs"])
        if probability is None:
            skipped[key] += 1
            continue
        predictions.append((probability, int(row["leader_won"]), key))
    if not predictions:
        return {
            "status": "insufficient_eligible_out_of_sample_data",
            "training_end": training_end, "test_start": test_start, "test_end": test_end,
            "minimum_games": minimum_games, "eligible_states": 0,
            "skipped_sparse_states": sum(skipped.values()), "by_bucket": {},
        }
    brier = sum((probability - outcome) ** 2 for probability, outcome, _ in predictions) / len(predictions)
    epsilon = 1e-12
    log_loss = -sum(
        outcome * math.log(max(epsilon, probability)) + (1 - outcome) * math.log(max(epsilon, 1 - probability))
        for probability, outcome, _ in predictions
    ) / len(predictions)
    by_bucket: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for probability, outcome, key in predictions:
        grouped[key].append((probability, outcome))
    for key, values in grouped.items():
        by_bucket[key] = {
            "states": len(values),
            "mean_predicted_probability": sum(value[0] for value in values) / len(values),
            "realized_win_rate": sum(value[1] for value in values) / len(values),
        }
    return {
        "status": "descriptive_probability_evaluation_only",
        "training_end": training_end, "test_start": test_start, "test_end": test_end,
        "minimum_games": minimum_games, "eligible_states": len(predictions),
        "skipped_sparse_states": sum(skipped.values()),
        "brier_score": brier, "log_loss": log_loss, "by_bucket": by_bucket,
        "trading_profitability_inference": "not_available_without_time-aligned Kalshi quote/fill data",
    }
