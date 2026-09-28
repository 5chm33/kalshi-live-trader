"""Synthetic-format tests; these records are never performance evidence."""
import unittest
from summarize_monitor import summarize


class SummaryTests(unittest.TestCase):
    def records(self):
        return [
            {'type': 'monitor_start', 'at': '2026-09-25T00:00:00Z',
             'duration_seconds': 1800, 'interval_seconds': 10},
            {'type': 'monitor_cycle', 'espn_ok': True, 'kalshi_ok': False,
             'observed_at': '2026-09-25T00:00:00Z',
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

    def test_suspended_runtime_is_not_reported_as_continuous_thirty_minutes(self):
        rows = self.records()
        rows[1]['kalshi_ok'] = True
        rows[1].pop('source_error')
        rows.insert(2, {'type': 'monitor_cycle', 'observed_at': '2026-09-25T03:00:00Z',
                        'espn_ok': True, 'kalshi_ok': True, 'real_orders': 0})
        rows[-1]['ended_at'] = '2026-09-25T03:00:01Z'
        rows[-1]['totals'].update(cycles=2, source_errors=0, kalshi_ok=2)
        text = summarize(rows)
        self.assertIn('| Sampling continuity | interrupted |', text)
        self.assertIn('wall-clock span', text)

    def test_book_errors_make_zero_signal_window_incomplete(self):
        rows = self.records()
        rows[1]['kalshi_ok'] = True
        rows[1].pop('source_error')
        rows[1]['quote_errors'] = 1
        rows[-1]['totals'].update(source_errors=0, kalshi_ok=1, quote_errors=1)
        text = summarize(rows)
        self.assertIn('| Incomplete/failed orderbooks | 1 |', text)
        self.assertIn('executable quotes were missing', text)
        rows[-1]['totals']['quote_errors'] = 0
        with self.assertRaisesRegex(ValueError, 'book error totals'):
            summarize(rows)

    def test_one_sided_books_are_real_but_not_executable(self):
        rows = self.records()
        rows[1].pop('source_error')
        rows[1].update(kalshi_ok=True, quote_errors=0, unusable_books=2)
        rows[-1]['totals'].update(kalshi_ok=1, source_errors=0,
                                   quote_errors=0, unusable_books=2)
        text = summarize(rows)
        self.assertIn('| One-sided/empty book snapshots (not executable) | 2 |', text)
        self.assertIn('illiquid markets', text)
        self.assertIn('Both public feeds remained readable', text)


if __name__ == '__main__':
    unittest.main()
