"""Static and CLI gates that prevent read-only collectors from drifting into writers."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from scripts.check_readonly_architecture import check, direct_violations


class ReadOnlyArchitectureTests(unittest.TestCase):
    def test_tracked_readonly_entrypoints_reach_no_writer_or_http_write_call(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(check(root), [])

    def test_direct_writer_import_or_post_call_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.py'
            path.write_text('from core.pilot_venue import ScopedVenue\nclient.post("x")\n')
            violations = direct_violations(path)
        self.assertTrue(any('writer import' in item for item in violations))
        self.assertTrue(any('post()' in item for item in violations))

    def test_live_flag_exits_before_observer_run(self):
        with patch.object(sys, 'argv', ['main.py', '--live']), patch('main.run') as run:
            with self.assertRaises(SystemExit):
                main.main()
        run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
