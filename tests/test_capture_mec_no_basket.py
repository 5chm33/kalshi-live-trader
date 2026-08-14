from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research.capture_mec_no_basket import run_cycle
from research.store import ResearchStore


class FakeReadOnlyClient:
    def get(self, path, params=None):
        if path == "/events":
            return {"events": [
                {"event_ticker": "KXMEC-1", "status": "open", "category": "Sports", "mutually_exclusive": True},
                {"event_ticker": "KXPOL-1", "status": "open", "category": "Politics", "mutually_exclusive": True},
            ]}
        if path == "/events/KXMEC-1":
            return {"markets": [
                {"ticker": "KXMEC-A", "status": "active", "market_type": "binary", "no_ask_dollars": "0.30"},
                {"ticker": "KXMEC-B", "status": "active", "market_type": "binary", "no_ask_dollars": "0.30"},
            ]}
        raise AssertionError(path)

    def orderbook(self, ticker):
        return {"orderbook_fp": {"yes_dollars": [["0.70", "2"]], "no_dollars": []}}


class CaptureMecNoBasketTests(unittest.TestCase):
    def test_collector_records_nonpolitical_mec_observation_without_order_api(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_cycle(FakeReadOnlyClient(), ResearchStore(Path(directory) / "research.sqlite3"), max_events=2)
            self.assertEqual(report["mode"], "paper_only_no_orders")
            self.assertEqual(report["events_scanned"], 1)
            self.assertEqual(report["political_blocked"], 1)
            self.assertEqual(report["eligible_events"], 1)
            self.assertEqual(report["observations_stored"], 1)


if __name__ == "__main__":
    unittest.main()
