"""Offline regression tests; never send a live order or require credentials."""
from __future__ import annotations

import io
import json
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

from core.espn_feed import ESPNFeed, GameState
from core.kalshi_client import KalshiClient
from core.market_matcher import MarketMatcher
from core.public_market import MarketDataError, PublicMarketClient, quote_from_orderbook
from main import estimated_taker_fee, observe_cycle
from strategies.latency_sniper import LatencySniper
from strategies.weather_ensemble import EnsembleForecast, EnsembleWeatherEngine


def market(team, occurrence="2026-09-25T20:05:00Z"):
    return {"ticker": f"KXMLBGAME-26SEP252005BALNYY-{team}",
            "event_ticker": "KXMLBGAME-26SEP252005BALNYY",
            "occurrence_datetime": occurrence, "status": "active",
            "yes_bid_dollars": "0.4500", "yes_ask_dollars": "0.5500"}


def book():
    return {"yes_dollars": [["0.4500", "9.00"]],
            "no_dollars": [["0.4900", "2.00"]]}


class QuoteTests(unittest.TestCase):
    def test_executable_quotes_and_size_from_opposite_bid(self):
        quote = quote_from_orderbook(book())
        self.assertEqual(quote.yes_ask, Decimal("0.5100"))
        self.assertEqual(quote.no_ask, Decimal("0.5500"))
        self.assertEqual(quote.yes_ask_size, Decimal("2.00"))
        self.assertEqual(quote.no_ask_size, Decimal("9.00"))
        self.assertLess(quote.yes_bid, quote.yes_ask)

    def test_one_sided_book_is_untradeable(self):
        self.assertIsNone(quote_from_orderbook({"yes_dollars": [["0.5", "1"]], "no_dollars": []}))
        self.assertIsNone(quote_from_orderbook({"yes_dollars": [], "no_dollars": []}))

    def test_malformed_and_crossed_books_fail(self):
        for raw in ({"yes_dollars": [["NaN", "1"]], "no_dollars": [["0.2", "1"]]},
                    {"yes_dollars": [["0.8", "1"]], "no_dollars": [["0.5", "1"]]},
                    {"yes_dollars": [["0.5", "-2"]], "no_dollars": []},
                    {"yes_dollars": [["0.5", "1"]]}):
            with self.subTest(raw=raw), self.assertRaises(MarketDataError):
                quote_from_orderbook(raw)

    def test_fee_rounding_is_ceiling(self):
        self.assertEqual(estimated_taker_fee(Decimal("0.50")), Decimal("0.02"))
        self.assertEqual(estimated_taker_fee(Decimal("0.50"), 100), Decimal("1.75"))


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.matcher = MarketMatcher(Mock())
        self.game = GameState(sport="mlb", game_id="real-game-id", team_a="BAL", team_b="NYY",
                              team_a_full="Baltimore Orioles", team_b_full="New York Yankees",
                              score_a=3, score_b=0, state="in", period=7,
                              event_time="2026-09-25T20:05:00Z")

    def test_does_not_match_next_day_same_teams(self):
        events = {"nextday": [market("BAL", "2026-09-26T20:05:00Z"),
                              market("NYY", "2026-09-26T20:05:00Z")]}
        self.assertIsNone(self.matcher._match_one(self.game, events))

    def test_exact_team_and_event_time_matches(self):
        matched = self.matcher._match_one(self.game, {"today": [market("BAL"), market("NYY")]})
        self.assertEqual(matched.market_a.team_key, "BAL")
        self.assertEqual(matched.market_b.team_key, "NYY")
        self.assertEqual(matched.event_time, self.game.event_time)

    def test_missing_start_time_is_not_safe(self):
        self.game.event_time = ""
        self.assertIsNone(self.matcher._match_one(self.game, {"x": [market("BAL"), market("NYY")]}))


class PortfolioTests(unittest.TestCase):
    def test_writes_are_blocked_before_network_and_auth(self):
        client = KalshiClient({})
        client.session.post = Mock(side_effect=AssertionError("network write occurred"))
        with self.assertRaises(RuntimeError):
            client.place_ioc("TEST", "bid", 1, 0.5)
        client.session.post.assert_not_called()

    def test_positions_failed_get_is_not_empty(self):
        client = KalshiClient({})
        client._request = Mock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
            client.get_positions()

    def test_balance_failure_is_not_a_zero_wallet(self):
        client = KalshiClient({})
        client._request = Mock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
            client.get_balance()
        with self.assertRaisesRegex(RuntimeError, "Cannot verify"):
            client.get_portfolio_value()

    def test_positions_read_all_pages(self):
        client = KalshiClient({})
        client._request = Mock(side_effect=[
            {"market_positions": [{"ticker": "A", "position_fp": "1"}], "cursor": "next"},
            {"market_positions": [{"ticker": "B", "position_fp": "-2"}], "cursor": ""}])
        self.assertEqual(len(client.get_positions()), 2)
        self.assertIn("cursor=next", client._request.call_args_list[-1].args[1])


class MarketPaginationTests(unittest.TestCase):
    def test_missing_page_fails_instead_of_returning_partial_data(self):
        session = Mock()
        first = Mock()
        first.json.return_value = {"markets": [{"ticker": "A"}], "cursor": "next"}
        broken = Mock()
        broken.json.return_value = {"error": "failure"}
        session.get.side_effect = [first, broken]
        with self.assertRaises(MarketDataError):
            PublicMarketClient(session).get_markets("KXMLBGAME")


class ESPNTests(unittest.TestCase):
    def test_http_error_does_not_reuse_old_scores(self):
        feed = ESPNFeed(sports=["mlb"])
        feed._cache[feed.URLS["mlb"]] = (["stale-data"], 0)
        response = Mock(status_code=503)
        response.raise_for_status.side_effect = RuntimeError("service unavailable")
        with patch("core.espn_feed.requests.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "aborting scan"):
                feed.poll()


class WeatherTests(unittest.TestCase):
    def test_missing_target_date_does_not_use_tomorrow(self):
        engine = EnsembleWeatherEngine()
        response = Mock(status_code=200)
        response.json.return_value = {"daily": {"time": ["2026-09-26"],
            "temperature_2m_max_member01_ecmwf_ifs025": [75]}}
        engine.session.get = Mock(return_value=response)
        forecast = engine.get_ensemble_probability("new_york", "2026-09-25", 70)
        self.assertIsNone(forecast.probability_above_threshold)

    def test_no_gaussian_fallback_from_point_forecast(self):
        engine = EnsembleWeatherEngine()
        forecast = EnsembleForecast(city="new_york", date="2026-09-25",
                                    forecast_type="high", nws_point_forecast=90)
        result = engine._calculate_probability(forecast, 80, "above")
        self.assertIsNone(result.probability_above_threshold)
        self.assertEqual(result.forecast_confidence, 0)

    def test_ukmo_members_in_probability(self):
        engine = EnsembleWeatherEngine()
        forecast = EnsembleForecast(city="new_york", date="2026-09-25",
                                    forecast_type="high", ecmwf_members=[60],
                                    ukmo_members=[80], ensemble_mean=70)
        result = engine._calculate_probability(forecast, 70, "above")
        self.assertEqual(result.total_members, 2)
        self.assertEqual(result.probability_above_threshold, 0.5)

    def test_unknown_city_and_bad_date_rejected(self):
        engine = EnsembleWeatherEngine()
        self.assertIsNone(engine._extract_city("KXHIGHTNYCXYZ-26SEP25-T70"))
        self.assertIsNone(engine._extract_date("KXHIGHTNYC-26FOO25-T70"))
        self.assertIsNone(engine._extract_date("KXHIGHTNYC-26FEB30-T70"))


class PipelineTests(unittest.TestCase):
    def test_read_only_candidate_uses_executable_book_and_logs_no_orders(self):
        game = GameState(sport="mlb", game_id="g", team_a="BAL", team_b="NYY",
                         team_a_full="Orioles", team_b_full="Yankees", score_a=3,
                         score_b=0, state="in", period=7,
                         event_time="2026-09-25T20:05:00Z")
        feed = Mock()
        feed.poll.return_value = ([game], [])
        client = Mock()
        client.get_markets.return_value = [market("BAL"), market("NYY")]
        client.get_orderbook.return_value = book()
        matcher = MarketMatcher(client)
        out = io.StringIO()
        result = observe_cycle(feed, matcher, client, LatencySniper(), out)
        self.assertEqual(result["strict_matches"], 1)
        self.assertEqual(result["heuristic_candidates"], 1)
        self.assertEqual(result["real_orders"], 0)
        self.assertEqual(json.loads(out.getvalue().splitlines()[-2])["best_ask"], "0.5100")
        client.place_order.assert_not_called()
        client.place_ioc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
