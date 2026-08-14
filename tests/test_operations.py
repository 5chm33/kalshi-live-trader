from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.backup import create_backup
from research.export_ledger import export
from research.models import SourceStamp
from research.store import ResearchStore
from research.verify_restore import verify


class OperationTests(unittest.TestCase):
    def test_backup_restore_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "data.sqlite3"
            store = ResearchStore(database)
            stamp = SourceStamp("test", datetime.now(timezone.utc), None, "payload")
            store.record_observation(stamp, "test", "one", {"value": 1})
            backup = create_backup(database, root / "backups", retain=2)
            restored = verify(Path(str(backup["backup"])))
            exported = export(database, root / "exports", retain=2)
            self.assertEqual("ok", restored["integrity_check"])
            self.assertEqual(1, restored["counts"]["observations"])
            self.assertTrue(Path(str(exported["export"])).exists())


if __name__ == "__main__":
    unittest.main()
