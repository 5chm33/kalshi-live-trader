"""Tennis research data-contract gate.

The previous bot claimed a first-set-loss strategy without validating set-level
state. V11 blocks the strategy until every required field is supplied by a
reliable score source.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class TennisObservation:
    match_id: str
    player_a: str
    player_b: str
    player_a_rank: int | None
    player_b_rank: int | None
    surface: str | None
    best_of_sets: int | None
    completed_sets: tuple[tuple[int, int], ...]
    current_set_games: tuple[int, int] | None
    status: str
    source: str


REQUIRED_FIELDS = (
    "match_id", "player_a", "player_b", "player_a_rank", "player_b_rank",
    "surface", "best_of_sets", "completed_sets", "current_set_games", "status", "source",
)


def validate_comeback_contract(observation: TennisObservation) -> tuple[bool, str]:
    """Return false unless a real first-set-loss condition is provable."""
    missing = [field for field in REQUIRED_FIELDS if getattr(observation, field) in (None, "", ())]
    if missing:
        return False, f"missing required tennis fields: {', '.join(missing)}"
    if observation.status.lower() not in {"live", "in progress"}:
        return False, "match is not live"
    if not observation.completed_sets:
        return False, "no completed set is available"
    first = observation.completed_sets[0]
    if len(first) != 2:
        return False, "invalid first-set score"
    return True, "tennis match-state contract complete"


def first_set_loser(observation: TennisObservation) -> str | None:
    """Return player identifier only after contract validation."""
    valid, _ = validate_comeback_contract(observation)
    if not valid:
        return None
    a_games, b_games = observation.completed_sets[0]
    if a_games == b_games:
        return None
    return observation.player_a if a_games < b_games else observation.player_b
