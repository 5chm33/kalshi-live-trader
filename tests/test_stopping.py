from __future__ import annotations

from datetime import datetime, timezone
import unittest

from research.stopping import StoppingRule, collection_status


class StoppingRuleTests(unittest.TestCase):
    def rule(self) -> StoppingRule:
        return StoppingRule.from_manifest({"collection_window": {
            "prospective_start_at": "2026-08-15T00:00:00+00:00",
            "prospective_end_at": "2026-12-31T23:59:59+00:00",
            "maximum_eligible_candidates": 250,
            "minimum_settled_candidates": 100,
        }})

    def test_budget_and_time_end_stop_collection(self) -> None:
        rule = self.rule()
        before = collection_status(rule, 0, 0, datetime(2026, 8, 14, tzinfo=timezone.utc))
        self.assertFalse(before["collect"])
        running = collection_status(rule, 1, 0, datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertTrue(running["collect"])
        budget = collection_status(rule, 250, 100, datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertFalse(budget["collect"])
        ended = collection_status(rule, 4, 3, datetime(2027, 1, 1, tzinfo=timezone.utc))
        self.assertFalse(ended["collect"])
        self.assertTrue(ended["retire_or_respecify"])


if __name__ == "__main__":
    unittest.main()
