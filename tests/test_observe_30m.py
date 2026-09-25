"""Fast, mocked, zero-network tests for the bounded live-data monitor."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from observe_30m import run


class MonitorTests(unittest.TestCase):
    def test_outage_still_runs_full_window_and_keeps_every_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.jsonl'
            tick = [0.0]
            def sleep(seconds):
                tick[0] += seconds
            feed = Mock()
            feed.poll.return_value = ([], [])
            matcher = Mock()
            matcher._get_markets.side_effect = RuntimeError('certificate invalid')
            with patch('observe_30m.time.monotonic', side_effect=lambda: tick[0]), \
                 patch('observe_30m.time.sleep', side_effect=sleep), \
                 patch('observe_30m.ESPNFeed', return_value=feed), \
                 patch('observe_30m.MarketMatcher', return_value=matcher):
                result = run(60, 10, path)
            rows = [json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual(result['totals']['cycles'], 6)
            self.assertEqual(result['totals']['source_errors'], 6)
            self.assertEqual(result['totals']['kalshi_ok'], 0)
            self.assertIsNone(result['win_rate'])
            self.assertTrue(all(r['real_orders'] == 0 for r in rows if r['type'] == 'monitor_cycle'))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_world_readable_or_symlink_journal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.jsonl'
            path.write_text('old\n')
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                run(60, 10, path)
            path.chmod(0o600)
            link = Path(tmp) / 'link.jsonl'
            link.symlink_to(path)
            with self.assertRaises(PermissionError):
                run(60, 10, link)


if __name__ == '__main__':
    unittest.main()
