"""Synthetic journal records are test fixtures, never trading-performance evidence."""
import unittest
from microstructure_report import summarize


class MicrostructureReportTests(unittest.TestCase):
    def test_zero_games_is_incomplete_and_zero_realized_return_undefined(self):
        rows = [{'type': 'study_start', 'start_at_utc': '2026-09-26T00:00:00Z',
                 'until_utc': '2026-10-02T00:00:00Z'}]
        report = summarize(rows)
        self.assertIn('0/120', report)
        self.assertIn('realized bot P&L: undefined', report)
        self.assertIn('not met or incomplete', report)

    def test_many_snapshots_are_one_game_and_no_fills(self):
        rows = [{'type': 'study_start', 'start_at_utc': '2026-09-26T00:00:00Z',
                 'until_utc': '2026-10-02T00:00:00Z'},
                {'type': 'event_selected', 'event_ticker': 'X',
                 'scheduled_start_utc': '2026-09-26T23:15:00Z'}]
        row = {'type': 'book_snapshot', 'event_ticker': 'X', 'sample_at_utc': '2026-09-26T22:45:00Z',
               'conditional_quote': {'eligible': True, 'conditional_paired_mark_dollars': '0.02'},
               'books': [{'before_utc': '2026-09-26T22:45:00Z', 'after_utc': '2026-09-26T22:45:00Z'},
                         {'before_utc': '2026-09-26T22:45:01Z', 'after_utc': '2026-09-26T22:45:01Z'}],
               'real_orders': 0, 'real_fills': 0}
        rows.extend([row] * 100)
        report = summarize(iter(rows))
        self.assertIn('100', report)
        self.assertIn('1/120', report)
        self.assertIn('0/120', report)
        self.assertIn('not met or incomplete', report)
        invalid = dict(row, books=[{'before_utc': '2026-09-26T22:45:10Z',
                                    'after_utc': '2026-09-26T22:45:10Z'}] * 2)
        invalid_report = summarize(iter(rows[:2] + [invalid]))
        self.assertIn('valid nearest-30-minute two-sided decision snapshot: **0**', invalid_report)
        rows[-1] = dict(row, real_orders=1)
        with self.assertRaises(ValueError): summarize(rows)

    def test_missing_start_or_duplicate_event_rejected(self):
        with self.assertRaises(ValueError): summarize([])
        start = {'type': 'study_start', 'start_at_utc': '2026-09-26T00:00:00Z',
                 'until_utc': '2026-10-02T00:00:00Z'}
        item = {'type': 'event_selected', 'event_ticker': 'X',
                'scheduled_start_utc': '2026-09-26T23:15:00Z'}
        with self.assertRaises(ValueError): summarize([start, item, item])

    def test_outsider_or_duplicate_settlement_rejected(self):
        start = {'type': 'study_start', 'start_at_utc': '2026-09-26T00:00:00Z',
                 'until_utc': '2026-10-02T00:00:00Z'}
        game = {'type': 'event_selected', 'event_ticker': 'A',
                'scheduled_start_utc': '2026-09-26T23:15:00Z'}
        paid = {'type': 'event_settlement', 'event_ticker': 'A', 'outcomes': [
                {'settlement_value_dollars': '0.0000'}, {'settlement_value_dollars': '1.0000'}]}
        with self.assertRaisesRegex(ValueError, 'cohort'):
            summarize(iter([start, game, dict(paid, event_ticker='OUTSIDER')]))
        with self.assertRaisesRegex(ValueError, 'Duplicate settlement'):
            summarize(iter([start, game, paid, paid]))


if __name__ == '__main__':
    unittest.main()
