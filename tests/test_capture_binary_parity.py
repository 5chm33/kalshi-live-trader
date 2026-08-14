from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research.capture_binary_parity import run_cycle
from research.store import ResearchStore


class FakeReadOnlyClient:
    def __init__(self):
        self.orderbook_calls = []

    def open_markets(self, limit: int):
        return {"markets": [
            {"ticker": "KXSAFE-1", "status": "open", "category": "Sports", "title": "Safe binary"},
            {"ticker": "KXPOL-1", "status": "open", "category": "Politics", "title": "Election result"},
        ]}

    def orderbook(self, ticker: str):
        self.orderbook_calls.append(ticker)
        return {"orderbook_fp": {"yes_dollars": [["0.60", "2"]], "no_dollars": [["0.60", "2"]]}}


class CaptureBinaryParityTests(unittest.TestCase):
    def test_collector_records_assessment_without_order_api(self):
        with tempfile.TemporaryDirectory() as directory:
            client = FakeReadOnlyClient()
            store = ResearchStore(Path(directory) / "research.sqlite3")
            report = run_cycle(client, store, max_markets=2)
            self.assertEqual(report["mode"], "paper_only_no_orders")
            self.assertEqual(report["markets_scanned"], 1)
            self.assertEqual(report["political_blocked"], 1)
            self.assertEqual(client.orderbook_calls, ["KXSAFE-1"])
            self.assertEqual(report["observations_stored"], 1)


if __name__ == "__main__":
    unittest.main()
