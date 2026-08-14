from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research.negative_results import NegativeResult
from research.store import ResearchStore


class NegativeResultsTests(unittest.TestCase):
    def result(self, reason: str = "negative_net") -> NegativeResult:
        return NegativeResult(
            strategy_family="mlb_late_lead", strategy_version="legacy_v1", hypothesis="test",
            specification_sha256="a" * 64, manifest_id=None,
            eligible_sample={"rows": 1}, exclusions={"none": True},
            uncertainty_interval={"kind": "unavailable"}, primary_outcome={"mean": "-0.01"},
            retirement_reason=reason, retired_at="2026-08-14T00:00:00+00:00",
            code_commit="abcdef1234567890", previous_result_sha256=None,
        )

    def test_append_only_negative_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchStore(Path(tmp) / "ledger.sqlite3")
            result = self.result()
            store.record_negative_result(result, "sig")
            store.record_negative_result(result, "sig")
            self.assertEqual(1, store.summary()["negative_results"])
            with self.assertRaises(ValueError):
                store.record_negative_result(self.result("rewritten_reason"), "sig")


if __name__ == "__main__":
    unittest.main()
