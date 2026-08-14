from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from research.execution_realism import TakerExecutionPolicy
from research.models import BookLevel, CanonicalBook, SourceStamp, StrategySignal
from research.paper_broker import PaperBroker


class ExecutionRealismTests(unittest.TestCase):
    def book(self, received_at: datetime) -> CanonicalBook:
        stamp = SourceStamp("test", received_at, received_at, "test-book")
        return CanonicalBook("T", (BookLevel(Decimal("0.40"), Decimal("2")),), (BookLevel(Decimal("0.60"), Decimal("2")),), stamp)

    def order(self) -> object:
        signal = StrategySignal(
            signal_id="s", strategy="test", strategy_version="v1", ticker="T", outcome_side="yes",
            model_probability=Decimal("0.70"), conservative_probability=Decimal("0.70"), observed_price=Decimal("0.41"),
            requested_contracts=Decimal("1"), source_stamp=SourceStamp("test", datetime.now(timezone.utc), None, "signal"),
            rationale="test", features={},
        )
        return PaperBroker().propose(signal)

    def test_stale_book_is_rejected_when_policy_enabled(self) -> None:
        now = datetime.now(timezone.utc)
        broker = PaperBroker(execution_policy=TakerExecutionPolicy(max_book_age_seconds=Decimal("1")))
        self.assertIsNone(broker.execute(self.order(), self.book(now - timedelta(seconds=2)), decision_at=now))

    def test_latency_haircut_is_applied_to_taker_fill(self) -> None:
        now = datetime.now(timezone.utc)
        policy = TakerExecutionPolicy(max_book_age_seconds=Decimal("1"), latency_seconds=Decimal("0.5"), adverse_price_per_second=Decimal("0.02"))
        broker = PaperBroker(execution_policy=policy)
        fill = broker.execute(self.order(), self.book(now), decision_at=now)
        self.assertIsNotNone(fill)
        assert fill is not None
        self.assertEqual(Decimal("0.41"), fill.average_price)  # YES takes 1-NO bid: .40 + .01 haircut
        self.assertEqual("taker_latency_stress_v1", fill.metadata["execution_model"])
        self.assertEqual("not_modeled", fill.metadata["maker_model"])


if __name__ == "__main__":
    unittest.main()
