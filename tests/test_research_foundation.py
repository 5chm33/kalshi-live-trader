from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.fees import estimate_fee
from research.guards import market_eligibility, paper_only_guard
from research.models import SourceStamp, StrategySignal, payload_hash
from research.orderbook import parse_orderbook
from research.paper_broker import PaperBroker
from research.store import ResearchStore


class ResearchFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        payload = {"fixture": True}
        self.stamp = SourceStamp(
            source="fixture",
            source_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
            received_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
            payload_sha256=payload_hash(payload),
        )
        self.book_payload = {
            "orderbook_fp": {
                "yes_dollars": [["0.40", "2.00"], ["0.45", "3.00"]],
                "no_dollars": [["0.30", "1.00"], ["0.35", "2.00"]],
            }
        }

    def test_documented_taker_fee_formula(self) -> None:
        # $0.57, 1 contract: ceil(1 * .07 * 1 * .57 * .43) = $0.0172.
        self.assertEqual(estimate_fee("0.57", "1", "1", "taker"), Decimal("0.0172"))
        self.assertEqual(estimate_fee("0.50", "100", "1", "taker"), Decimal("1.7500"))

    def test_binary_book_yes_no_conversion(self) -> None:
        book = parse_orderbook("TEST", self.book_payload, self.stamp)
        self.assertEqual(book.best_yes_bid, Decimal("0.45"))
        self.assertEqual(book.best_no_bid, Decimal("0.35"))
        self.assertEqual(book.best_yes_ask, Decimal("0.65"))
        self.assertEqual(book.best_no_ask, Decimal("0.55"))
        self.assertEqual(book.yes_spread, Decimal("0.20"))

    def test_paper_broker_partial_fill_respects_opposite_depth(self) -> None:
        book = parse_orderbook("TEST", self.book_payload, self.stamp)
        signal = StrategySignal(
            signal_id="signal-1",
            strategy="unit",
            strategy_version="unit-v1",
            ticker="TEST",
            outcome_side="yes",
            model_probability=Decimal("0.90"),
            conservative_probability=Decimal("0.85"),
            observed_price=Decimal("0.65"),
            requested_contracts=Decimal("5.00"),
            source_stamp=self.stamp,
            rationale="test",
            features={},
        )
        broker = PaperBroker("1")
        order = broker.propose(signal, "0.70")
        fill = broker.execute(order, book)
        self.assertIsNotNone(fill)
        assert fill is not None
        # Long YES consumes 2 NO-bid contracts at 65c, then 1 at 70c.
        self.assertEqual(fill.filled_contracts, Decimal("3.00"))
        self.assertEqual(fill.average_price, Decimal("0.6666666666666666666666666667"))
        self.assertGreater(fill.estimated_fee, Decimal("0"))
        self.assertEqual(fill.metadata["partial_fill"], "true")

    def test_paper_broker_rejects_unfillable_order(self) -> None:
        book = parse_orderbook("TEST", self.book_payload, self.stamp)
        signal = StrategySignal(
            signal_id="signal-2", strategy="unit", strategy_version="unit-v1", ticker="TEST",
            outcome_side="yes", model_probability=Decimal("0.9"),
            conservative_probability=Decimal("0.85"), observed_price=Decimal("0.60"),
            requested_contracts=Decimal("1"), source_stamp=self.stamp, rationale="test", features={},
        )
        self.assertIsNone(PaperBroker().execute(PaperBroker().propose(signal, "0.60"), book))

    def test_political_and_live_mode_are_hard_blocked(self) -> None:
        self.assertFalse(paper_only_guard("live").allowed)
        self.assertFalse(market_eligibility(
            {"status": "open", "series_ticker": "KXPRES", "title": "Presidential election"},
            ["KXMLBGAME"],
        ).allowed)

    def test_store_is_idempotent_for_raw_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "research.sqlite3")
            payload = {"value": 1}
            self.assertTrue(store.record_observation(self.stamp, "fixture", "one", payload))
            self.assertFalse(store.record_observation(self.stamp, "fixture", "one", payload))
            self.assertEqual(store.summary()["observations"], 1)


if __name__ == "__main__":
    unittest.main()
