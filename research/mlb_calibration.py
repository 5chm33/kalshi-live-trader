"""Empirical, game-clustered MLB late-lead calibration study.

This module creates a transparent research artifact from completed official MLB
games. It does not produce an order, and it returns no probability for a bucket
that fails a pre-registered minimum sample requirement.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MODEL_VERSION = "mlb_empirical_late_lead_v1"


def _key(inning: int, inning_half: str, leader_is_home: bool, lead_runs: int) -> str:
    # Cap extra innings and large leads to avoid artificial sparse buckets.
    return f"i{min(inning, 9)}_{inning_half}_home{int(leader_is_home)}_lead{min(lead_runs, 5)}"


def wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    p = wins / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total)
    return max(0.0, (centre - margin) / denominator)


@dataclass(frozen=True)
class Bucket:
    key: str
    games: int
    wins: int
    empirical_probability: float
    conservative_probability: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "games": self.games,
            "wins": self.wins,
            "empirical_probability": self.empirical_probability,
            "conservative_probability": self.conservative_probability,
        }


class EmpiricalMLBModel:
    """Versioned lookup model trained only from an explicit historical cutoff."""

    def __init__(self, buckets: dict[str, Bucket], minimum_games: int, training_end: str):
        self.buckets = buckets
        self.minimum_games = minimum_games
        self.training_end = training_end

    @classmethod
    def fit(cls, database: str | Path, training_end: str, minimum_games: int = 100) -> "EmpiricalMLBModel":
        if minimum_games < 30:
            raise ValueError("minimum_games must be at least 30")
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        # First observation per game+bucket avoids turning a long inning into
        # multiple independent samples of the same eventual result.
        rows = conn.execute(
            """WITH ranked AS (
                   SELECT *, ROW_NUMBER() OVER (
                     PARTITION BY game_pk, inning, inning_half, leader_is_home,
                                  CASE WHEN lead_runs > 5 THEN 5 ELSE lead_runs END
                     ORDER BY at_bat_index
                   ) AS rn
                   FROM mlb_historical_states
                   WHERE game_date <= ?
                 ) SELECT * FROM ranked WHERE rn = 1""",
            (training_end,),
        ).fetchall()
        grouped: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for row in rows:
            bucket = _key(row["inning"], row["inning_half"], bool(row["leader_is_home"]), row["lead_runs"])
            grouped[bucket][0] += 1
            grouped[bucket][1] += int(row["leader_won"])
        buckets: dict[str, Bucket] = {}
        for bucket, (games, wins) in grouped.items():
            probability = wins / games
            buckets[bucket] = Bucket(bucket, games, wins, probability, wilson_lower_bound(wins, games))
        return cls(buckets, minimum_games, training_end)

    def probability(self, inning: int, inning_half: str, leader_is_home: bool, lead_runs: int) -> float | None:
        bucket = self.buckets.get(_key(inning, inning_half, leader_is_home, lead_runs))
        if bucket is None or bucket.games < self.minimum_games:
            return None
        return bucket.conservative_probability

    def report(self) -> dict[str, Any]:
        eligible = {key: value.to_dict() for key, value in self.buckets.items() if value.games >= self.minimum_games}
        return {
            "model_version": MODEL_VERSION,
            "training_end": self.training_end,
            "minimum_games": self.minimum_games,
            "total_buckets": len(self.buckets),
            "eligible_buckets": eligible,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.report(), indent=2, sort_keys=True), encoding="utf-8")
