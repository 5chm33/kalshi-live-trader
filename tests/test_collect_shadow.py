"""No-network tests for the finite restart-safe research collector."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import json
import os
import unittest

from collect_shadow import collect


class CollectorTests(unittest.TestCase):
    def test_single_real_segment_is_journaled_without_order_method(self):
        now = datetime(2026, 9, 26, tzinfo=timezone.utc)
        clock = [now, now, now, now+timedelta(seconds=61), now+timedelta(seconds=61)]
        def fake_run(duration, interval, path):
            self.assertEqual((duration, interval), (61, 10))
            path.write_text(json.dumps({'type':'monitor_start'})+'\n')
            return {'totals': {'cycles': 1, 'candidates': 0, 'source_errors': 0, 'real_orders': 0}}
        with TemporaryDirectory() as tmp, patch('collect_shadow.utcnow', side_effect=clock), \
             patch('collect_shadow.run', side_effect=fake_run) as run_mock, \
             patch('collect_shadow.summarize', return_value='# real journal\n'):
            dest=Path(tmp)/'private'
            self.assertEqual(collect(now+timedelta(seconds=61),dest,interval=10),0)
            self.assertEqual(dest.stat().st_mode & 0o777, 0o700)
            self.assertEqual(len(list(dest.glob('*.jsonl'))),1)
            self.assertEqual(len(list(dest.glob('*.md'))),1)
            self.assertEqual(run_mock.call_count,1)

    def test_invalid_deadline_or_shared_directory_fails_closed(self):
        now=datetime.now(timezone.utc)
        with TemporaryDirectory() as tmp:
            dest=Path(tmp)/'shared';dest.mkdir();dest.chmod(0o755)
            with self.assertRaises(PermissionError):
                collect(now+timedelta(minutes=2),dest)
            with self.assertRaises(ValueError):
                collect(now+timedelta(days=9),Path(tmp)/'future')
            with self.assertRaises(ValueError):
                collect(now.replace(tzinfo=None),Path(tmp)/'naive')

    def test_uncompleted_segment_cannot_be_called_clean(self):
        now=datetime(2026,9,26,tzinfo=timezone.utc)
        clock=[now,now,now]
        def broken_run(_duration,_interval,path):
            path.write_text('{"type":"monitor_start"}\n')
            raise RuntimeError('data source failed')
        with TemporaryDirectory() as tmp, patch('collect_shadow.utcnow', side_effect=clock), \
             patch('collect_shadow.run', side_effect=broken_run):
            dest=Path(tmp)/'private'
            with self.assertRaisesRegex(RuntimeError,'data source failed'):
                collect(now+timedelta(seconds=61),dest)
            self.assertEqual(len(list(dest.glob('*.jsonl'))),1)
            self.assertEqual(len(list(dest.glob('*.md'))),0)


if __name__=='__main__':
    unittest.main()
