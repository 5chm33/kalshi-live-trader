"""Offline format tests; synthetic records here are never performance evidence."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from forward_evidence import report


def segment(*, orders=0, unusable=2):
    return [
        {'type': 'monitor_start', 'at': '2026-09-26T00:00:00+00:00',
         'duration_seconds': 60, 'interval_seconds': 60, 'execution': 'read_only'},
        {'type': 'unusable_book', 'ticker': 'FAKE', 'reason': 'one_sided_or_empty'},
        {'type': 'monitor_cycle', 'observed_at': '2026-09-26T00:00:00+00:00',
         'espn_ok': True, 'kalshi_ok': True, 'quote_errors': 0,
         'unusable_books': unusable, 'two_sided_game_pairs': 0,
         'real_orders': orders},
        {'type': 'monitor_end', 'ended_at': '2026-09-26T00:01:00+00:00',
         'elapsed_seconds': 60.0, 'totals': {
             'cycles': 1, 'espn_ok': 1, 'kalshi_ok': 1, 'source_errors': 0,
             'quote_errors': 0, 'unusable_books': unusable,
             'strict_matches': 1, 'two_sided_game_pairs': 0,
             'candidates': 0, 'real_orders': orders}},
    ]


class ForwardReportTests(unittest.TestCase):
    def test_complete_public_data_is_not_profit(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'complete.jsonl'
            path.write_text(''.join(json.dumps(x) + '\n' for x in segment()))
            incomplete = Path(tmp) / 'partial.jsonl'
            incomplete.write_text(json.dumps(segment()[0]) + '\n')
            text = report(Path(tmp))
        self.assertIn('Completed, structurally valid segments: **1**; unfinished segments: **1**', text)
        self.assertIn('unavailable (no observed exits)', text)
        self.assertIn('Actual bot orders: **0**', text)
        self.assertIn('LIVE TRADING DISABLED', text)

    def test_claimed_live_order_cannot_be_reclassified_as_shadow(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / 'bad.jsonl').write_text(
                ''.join(json.dumps(x) + '\n' for x in segment(orders=1)))
            with self.assertRaisesRegex(ValueError, 'unexpectedly claims actual bot orders'):
                report(Path(tmp))

    def test_no_records_fails_closed(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'No real forward'):
                report(Path(tmp))

    def test_legacy_one_sided_books_are_reclassified_but_not_scored(self):
        rows = segment(unusable=0)
        rows[1] = {'type': 'quote_error', 'ticker': 'FAKE',
                   'error': 'One-sided or empty executable book'}
        rows[2]['quote_errors'] = 1
        rows[2].pop('two_sided_game_pairs')
        rows[-1]['totals']['quote_errors'] = 1
        rows[-1]['totals'].pop('two_sided_game_pairs')
        with TemporaryDirectory() as tmp:
            (Path(tmp) / 'legacy.jsonl').write_text(
                ''.join(json.dumps(r) + '\n' for r in rows))
            text = report(Path(tmp))
        self.assertIn('failed/malformed book reads: **0**', text)
        self.assertIn('one-sided or empty book snapshots (not executable): **1**', text.lower())
        self.assertIn('unknown (not measured in completed legacy segments)', text)
        self.assertIn('1 segments could not be completely scored', text)


if __name__ == '__main__':
    unittest.main()
