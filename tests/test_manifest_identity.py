from __future__ import annotations

import json
import unittest
from pathlib import Path

from research.audit import StrategyManifest


class ManifestIdentityTests(unittest.TestCase):
    def test_file_manifest_has_pinned_created_at_and_stable_identity(self) -> None:
        path = Path("manifests/weather_settlement_mapped_v1_0_2.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("created_at", payload)
        first = StrategyManifest(**payload)
        second = StrategyManifest(**payload)
        self.assertEqual(first.manifest_id, second.manifest_id)


if __name__ == "__main__":
    unittest.main()
