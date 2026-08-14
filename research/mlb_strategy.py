"""MLB late-lead hypothesis detector for research collection.

This module deliberately does not invent a win probability. It identifies
well-defined game states, links them to a valid Kalshi contract, and records the
executable quote. A calibrated probability model must be supplied separately
before it can emit a paper order candidate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from research.models import CanonicalBook, GameState, MarketMapping, StrategySignal


@dataclass(frozen=True)
class MLBLateLeadCandidate:
    candidate_id: str
    game_id: str
    ticker: str
    leader: str
    inning: int
    lead_runs: int
    executable_yes_ask: Decimal
    spread: Decimal | None
    state: GameState
    mapping: MarketMapping

    def to_features(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "game_id": self.game_id,
            "leader": self.leader,
            "inning": self.inning,
            "lead_runs": self.lead_runs,
            "executable_yes_ask": str(self.executable_yes_ask),
            "spread": str(self.spread) if self.spread is not None else None,
            "mapping_method": self.mapping.mapping_method,
            "mapping_confidence": str(self.mapping.confidence),
            "away_team": self.state.away_team,
            "home_team": self.state.home_team,
            "away_runs": self.state.away_runs,
            "home_runs": self.state.home_runs,
            "inning_half": self.state.inning_half,
        }


class WinProbabilityModel(Protocol):
    version: str

    def conservative_probability(self, candidate: MLBLateLeadCandidate) -> Decimal | None:
        """Return a calibrated lower-bound probability, or None when unavailable."""


class NoProbabilityModel:
    version = "disabled-no-calibration"

    def conservative_probability(self, candidate: MLBLateLeadCandidate) -> Decimal | None:
        return None


class MLBLateLeadDetector:
    version = "mlb-late-lead-detector-v1"

    def __init__(self, min_inning: int = 6, min_run_lead: int = 3):
        self.min_inning = min_inning
        self.min_run_lead = min_run_lead

    def detect(self, game: GameState, mapping: MarketMapping, book: CanonicalBook) -> MLBLateLeadCandidate | None:
        if game.status != "Live" or game.inning is None:
            return None
        if game.inning < self.min_inning:
            return None
        leader = game.leader
        if leader is None or leader != mapping.team:
            return None
        if abs(game.lead) < self.min_run_lead:
            return None
        if mapping.ticker != book.ticker or book.best_yes_ask is None:
            return None
        return MLBLateLeadCandidate(
            candidate_id=f"mlb-state-{uuid4()}",
            game_id=game.source_game_id,
            ticker=mapping.ticker,
            leader=leader,
            inning=game.inning,
            lead_runs=abs(game.lead),
            executable_yes_ask=book.best_yes_ask,
            spread=book.yes_spread,
            state=game,
            mapping=mapping,
        )

    def to_signal(
        self,
        candidate: MLBLateLeadCandidate,
        model: WinProbabilityModel,
        requested_contracts: Decimal,
    ) -> StrategySignal | None:
        """Convert a candidate only if an explicitly calibrated model is available."""
        probability = model.conservative_probability(candidate)
        if probability is None:
            return None
        return StrategySignal(
            signal_id=f"signal-{uuid4()}",
            strategy="mlb_late_lead",
            strategy_version=f"{self.version}+{model.version}",
            ticker=candidate.ticker,
            outcome_side="yes",
            model_probability=probability,
            conservative_probability=probability,
            observed_price=candidate.executable_yes_ask,
            requested_contracts=requested_contracts,
            source_stamp=candidate.state.stamp,
            rationale=(
                f"Research candidate: {candidate.leader} leads by {candidate.lead_runs} "
                f"in inning {candidate.inning}; model={model.version}"
            ),
            features=candidate.to_features(),
        )
