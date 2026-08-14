from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.audit import AuditSigner, DecisionRecord, StrategyManifest, sha256
from research.store import ResearchStore


class AuditRecordTests(unittest.TestCase):
    def manifest(self) -> StrategyManifest:
        return StrategyManifest(
            strategy_family="weather_settlement_mapped",
            strategy_version="v1.0.0",
            hypothesis="A calibrated station-mapped forecast has positive net settlement expectancy.",
            market_universe={"series": ["KXHIGHNY"], "frozen_at": "2026-08-14T00:00:00+00:00"},
            feature_schema={"target_date": "iso-date", "ensemble_members": "decimal[]"},
            training_start="2025-01-01T00:00:00+00:00", training_end="2025-12-31T23:59:59+00:00",
            holdout_start="2026-01-01T00:00:00+00:00", holdout_end="2026-06-30T23:59:59+00:00",
            first_prospective_at="2026-07-01T00:00:00+00:00",
            primary_metric="one-sided 95% lower confidence bound of net dollars per contract",
            confidence_interval_method="cluster bootstrap by settlement date",
            lower_confidence_bound_threshold="0.00", calibration_error_limit="0.02",
            max_variants=1, execution_lifecycle="entry_to_settlement", code_commit="deadbee",
        )

    def test_manifest_rejects_training_after_first_prospective(self) -> None:
        manifest = self.manifest()
        bad = StrategyManifest(**{**manifest.payload, "first_prospective_at": "2025-01-01T00:00:00+00:00"})
        with self.assertRaises(ValueError):
            _ = bad.manifest_id

    def test_manifest_requires_explicit_code_commit(self) -> None:
        bad = StrategyManifest(**{**self.manifest().payload, "code_commit": "unavailable"})
        with self.assertRaises(ValueError):
            _ = bad.manifest_id

    def test_append_only_chain_and_signed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ResearchStore(Path(tmp) / "ledger.sqlite3")
            manifest = self.manifest()
            store.record_manifest(manifest)
            dataset_sha = sha256({"rows": 1, "as_of": "2026-08-14"})
            record = DecisionRecord(
                manifest_id=manifest.manifest_id, stage="pre_registered", dataset_sha256=dataset_sha,
                available_data_ends_at="2026-08-14T00:00:00+00:00", decision_timestamp="2026-08-14T00:00:00+00:00",
                exclusions={"missing_timestamps": "exclude"}, primary_endpoint=manifest.primary_metric,
                promotion_rule="LCB > 0", retirement_rule="LCB <= 0 after registered sample", more_data_rule="insufficient N",
                falsifier="negative lower confidence bound",
            )
            signer = AuditSigner(b"unit-test-key")
            signature = signer.sign(record.record_sha256)
            store.record_decision_record(record, signature)
            result = {"label": "non_executable", "net_dollars_per_contract": "-0.01"}
            snapshot_sha = sha256({"record": record.record_sha256, "result": result, "dataset": dataset_sha})
            store.record_evaluation_snapshot(snapshot_sha, manifest.manifest_id, record.record_sha256, dataset_sha, "test", result, signer.sign(snapshot_sha))
            self.assertTrue(signer.verify(record.record_sha256, signature))
            self.assertEqual(1, store.summary()["strategy_manifests"])
            self.assertEqual(1, store.summary()["decision_records"])
            self.assertEqual(1, store.summary()["evaluation_snapshots"])
            with self.assertRaises(ValueError):
                store.record_evaluation_snapshot(snapshot_sha, manifest.manifest_id, record.record_sha256, dataset_sha, "test", {"changed": True}, signer.sign(snapshot_sha))


if __name__ == "__main__":
    unittest.main()
