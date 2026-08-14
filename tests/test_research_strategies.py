from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from research.mlb_matcher import match_game_markets
from research.mlb_strategy import MLBLateLeadDetector, NoProbabilityModel
from research.models import GameState, SourceStamp, payload_hash
from research.orderbook import parse_orderbook
from research.tennis import TennisObservation, first_set_loser, validate_comeback_contract
from research.weather import WeatherMarketDefinition, parse_ensemble_payload


class StrategyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        payload = {"kind": "fixture"}
        self.stamp = SourceStamp(
            source="fixture",
            source_at=None,
            received_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
            payload_sha256=payload_hash(payload),
        )

    def test_mlb_matcher_requires_distinct_exact_ticker_suffixes(self) -> None:
        game = GameState(
            source_game_id="game-1", league="MLB", status="Live",
            away_team="New York Yankees", home_team="Toronto Blue Jays",
            away_runs=4, home_runs=1, inning=8, inning_half="Top",
            scheduled_innings=9, stamp=self.stamp, raw={},
        )
        markets = [
            {"series_ticker": "KXMLBGAME", "ticker": "KXMLBGAME-TESTNYYTOR-NYY"},
            {"series_ticker": "KXMLBGAME", "ticker": "KXMLBGAME-TESTNYYTOR-TOR"},
            {"series_ticker": "KXMLBGAME", "ticker": "KXMLBGAME-OTHERNYYSF-NYY"},
        ]
        mappings = match_game_markets(game, markets)
        self.assertEqual({item.team for item in mappings}, {"New York Yankees", "Toronto Blue Jays"})
        self.assertEqual({item.ticker for item in mappings}, {
            "KXMLBGAME-TESTNYYTOR-NYY", "KXMLBGAME-TESTNYYTOR-TOR",
        })

    def test_mlb_candidate_cannot_become_signal_without_calibration(self) -> None:
        game = GameState(
            source_game_id="game-1", league="MLB", status="Live",
            away_team="New York Yankees", home_team="Toronto Blue Jays",
            away_runs=4, home_runs=1, inning=8, inning_half="Top",
            scheduled_innings=9, stamp=self.stamp, raw={},
        )
        mapping = match_game_markets(game, [
            {"series_ticker": "KXMLBGAME", "ticker": "KXMLBGAME-TESTNYYTOR-NYY"},
            {"series_ticker": "KXMLBGAME", "ticker": "KXMLBGAME-TESTNYYTOR-TOR"},
        ])[0]
        # Choose the Yankees mapping, not the Toronto mapping.
        mapping = next(item for item in match_game_markets(game, [
            {"series_ticker": "KXMLBGAME", "ticker": "KXMLBGAME-TESTNYYTOR-NYY"},
            {"series_ticker": "KXMLBGAME", "ticker": "KXMLBGAME-TESTNYYTOR-TOR"},
        ]) if item.team == "New York Yankees")
        book = parse_orderbook("KXMLBGAME-TESTNYYTOR-NYY", {
            "orderbook_fp": {"yes_dollars": [["0.60", "2"]], "no_dollars": [["0.35", "2"]]}
        }, self.stamp)
        candidate = MLBLateLeadDetector().detect(game, mapping, book)
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertIsNone(MLBLateLeadDetector().to_signal(candidate, NoProbabilityModel(), Decimal("1")))

    def test_weather_parser_counts_actual_members_by_model(self) -> None:
        payload = {
            "daily": {
                "time": ["2026-08-14"],
                "temperature_2m_max_icon_seamless_eps": [100.0],
                "temperature_2m_max_member01_icon_seamless_eps": [101.0],
                "temperature_2m_max_member01_ncep_gefs_seamless": [99.0],
                "temperature_2m_max_member02_ncep_gefs_seamless": [None],
            }
        }
        snapshot = parse_ensemble_payload("dallas", "2026-08-14", "temperature_2m_max", payload, self.stamp)
        self.assertEqual(snapshot.member_count, 3)
        self.assertEqual(len(snapshot.members_by_model["icon_seamless_eps"]), 2)
        self.assertEqual(len(snapshot.members_by_model["ncep_gefs_seamless"]), 1)

    def test_weather_market_type_uses_floor_cap_only(self) -> None:
        self.assertEqual(WeatherMarketDefinition.from_market(
            {"ticker": "X", "title": "irrelevant", "floor_strike": 50, "cap_strike": 51}, "high"
        ).market_kind, "range")
        self.assertEqual(WeatherMarketDefinition.from_market(
            {"ticker": "X", "floor_strike": 50}, "high"
        ).market_kind, "above")
        self.assertEqual(WeatherMarketDefinition.from_market(
            {"ticker": "X", "cap_strike": 50}, "low"
        ).market_kind, "below")

    def test_tennis_contract_blocks_missing_first_set_context(self) -> None:
        incomplete = TennisObservation(
            match_id="x", player_a="A", player_b="B", player_a_rank=10, player_b_rank=100,
            surface="hard", best_of_sets=3, completed_sets=(), current_set_games=(2, 2),
            status="live", source="fixture",
        )
        self.assertFalse(validate_comeback_contract(incomplete)[0])
        self.assertIsNone(first_set_loser(incomplete))

        complete = TennisObservation(
            match_id="x", player_a="A", player_b="B", player_a_rank=10, player_b_rank=100,
            surface="hard", best_of_sets=3, completed_sets=((4, 6),), current_set_games=(1, 0),
            status="live", source="fixture",
        )
        self.assertTrue(validate_comeback_contract(complete)[0])
        self.assertEqual(first_set_loser(complete), "A")


if __name__ == "__main__":
    unittest.main()
