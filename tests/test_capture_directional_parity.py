from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research.capture_directional_parity import run_cycle
from research.store import ResearchStore


class FakeReadOnlyClient:
    def get(self, path, params=None):
        if path == "/events":
            return {"events": [{"event_ticker": "KXDIR-1", "status": "open", "category": "Economy", "mutually_exclusive": False, "title": "Threshold event"}]}
        if path == "/events/KXDIR-1":
            return {"markets": [
                {"ticker": "KXDIR-LOW", "status": "active", "market_type": "binary", "floor_strike": 50, "cap_strike": None},
                {"ticker": "KXDIR-HIGH", "status": "active", "market_type": "binary", "floor_strike": 60, "cap_strike": None},
            ]}
        raise AssertionError(path)

    def orderbook(self, ticker):
        if ticker == "KXDIR-LOW":
            return {"orderbook_fp": {"yes_dollars": [], "no_dollars": [["0.70", "2"]]}}
        return {"orderbook_fp": {"yes_dollars": [["0.70", "2"]], "no_dollars": []}}


class CaptureDirectionalParityTests(unittest.TestCase):
    def test_collector_records_structural_cover_without_order_api(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run_cycle(FakeReadOnlyClient(), ResearchStore(Path(directory) / "research.sqlite3"), max_events=1)
            self.assertEqual(report["mode"], "paper_only_no_orders")
            self.assertEqual(report["structural_events"], 1)
            self.assertEqual(report["pairs_assessed"], 1)
            self.assertEqual(report["observations_stored"], 1)


if __name__ == "__main__":
    unittest.main()
