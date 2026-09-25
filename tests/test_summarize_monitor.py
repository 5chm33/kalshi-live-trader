"""Synthetic-format tests; these records are never performance evidence."""
import unittest
from summarize_monitor import summarize


class SummaryTests(unittest.TestCase):
    def records(self):
        return [
            {'type': 'monitor_start', 'at': '2026-09-25T00:00:00Z',
             'duration_seconds': 1800},
            {'type': 'monitor_cycle', 'espn_ok': True, 'kalshi_ok': False,
             'source_error': 'Kalshi: SSLError certificate invalid', 'real_orders': 0},
            {'type': 'monitor_end', 'ended_at': '2026-09-25T00:30:00Z',
             'elapsed_seconds': 1800.1, 'totals': {
                 'cycles': 1, 'espn_ok': 1, 'kalshi_ok': 0,
                 'source_errors': 1, 'strict_matches': 0,
                 'candidates': 0, 'real_orders': 0}}]

    def test_outage_cannot_be_passing_or_profitable(self):
        text = summarize(self.records())
        self.assertIn('| TLS/certificate failures | 1 |', text)
        self.assertIn('win rate and realized bot P&L are undefined', text)
        self.assertIn('cannot validate a trading signal', text)

    def test_missing_end_or_shortened_window_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            summarize(self.records()[:-1])
        rows = self.records()
        rows[-1]['elapsed_seconds'] = 100
        with self.assertRaisesRegex(ValueError, 'duration'):
            summarize(rows)

    def test_any_nonzero_order_or_wrong_cycle_count_is_rejected(self):
        rows = self.records()
        rows[-1]['totals']['cycles'] = 2
        with self.assertRaises(ValueError):
            summarize(rows)
        rows = self.records()
        rows[1]['real_orders'] = 1
        with self.assertRaisesRegex(ValueError, 'cannot attribute'):
            summarize(rows)


if __name__ == '__main__':
    unittest.main()
