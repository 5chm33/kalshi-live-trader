"""Synthetic journal records are test fixtures, never trading-performance evidence."""
import unittest
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from microstructure_report import load_validated_rows, summarize


class MicrostructureReportTests(unittest.TestCase):
    def test_zero_games_is_incomplete_and_zero_realized_return_undefined(self):
        rows = [{'type': 'study_start', 'start_at_utc': '2026-09-26T00:00:00Z',
                 'until_utc': '2026-10-02T00:00:00Z'}]
        report = summarize(rows)
        self.assertIn('0/120', report)
        self.assertIn('realized bot P&L: undefined', report)
        self.assertIn('not met or incomplete', report)

    def test_future_game_has_pending_not_missing_decision(self):
        start = {'type': 'study_start', 'start_at_utc': '2026-09-26T00:00:00Z',
                 'until_utc': '2026-10-02T00:00:00Z'}
        event = {'type': 'event_selected', 'event_ticker': 'X',
                 'scheduled_start_utc': '2026-09-26T23:15:00Z'}
        result = summarize([start, event], as_of=datetime(2026, 9, 26, 7, tzinfo=timezone.utc))
        self.assertIn('Future decision times not yet reached: 1; missing after due: 0', result)

    def test_off_window_book_does_not_replace_missing_decision(self):
        start = {'type': 'study_start', 'start_at_utc': '2026-09-26T00:00:00Z',
                 'until_utc': '2026-10-02T00:00:00Z'}
        event = {'type': 'event_selected', 'event_ticker': 'X',
                 'scheduled_start_utc': '2026-09-26T23:15:00Z'}
        book = {'type': 'book_snapshot', 'event_ticker': 'X', 'sample_at_utc': '2026-09-26T22:15:00Z',
                'real_orders': 0, 'real_fills': 0, 'conditional_quote': {'eligible': True}}
        result = summarize(iter([start, event, book] * 1), as_of=datetime(2026, 9, 27, tzinfo=timezone.utc))
        self.assertIn('Actual book snapshots: 1', result)
        self.assertIn('missing after due: 1', result)

    def test_finalized_market_is_not_a_trade_or_valid_fixed_quote(self):
        rows = [{'type': 'study_start', 'start_at_utc': '2026-09-26T00:00:00Z',
                 'until_utc': '2026-10-02T00:00:00Z'},
                {'type': 'event_selected', 'event_ticker': 'X',
                 'scheduled_start_utc': '2026-09-26T23:15:00Z'},
                {'type': 'book_ineligible', 'event_ticker': 'X',
                 'reason': 'winner_market_inactive', 'statuses': ['active', 'finalized'],
                 'real_orders': 0, 'real_fills': 0}]
        report = summarize(rows, as_of=datetime(2026, 9, 27, tzinfo=timezone.utc))
        self.assertIn('Explicit inactive-market observations: 1', report)
        self.assertIn('valid nearest-30-minute two-sided decision snapshot: **0**', report)
        self.assertIn('missing after due: 1', report)
        with self.assertRaisesRegex(ValueError, 'Malformed'):
            summarize(rows[:2] + [dict(rows[2], real_orders=1)])

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

    def test_cli_loader_rejects_substituted_or_post_terminal_collector_state(self):
        registration={'type':'study_start','start_at_utc':'2026-09-26T00:00:00Z',
                      'until_utc':'2026-09-27T00:00:00Z','series_ticker':'KXMLBGAME',
                      'max_events':120,'order_writes_enabled':False,'real_orders':0,'real_fills':0}
        event={'type':'event_selected','event_ticker':'X','observed_at_utc':'2026-09-26T01:00:00Z',
               'scheduled_start_utc':'2026-09-26T01:30:00Z','real_orders':0,'real_fills':0}
        end={'type':'study_end','real_orders':0,'real_fills':0}
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'journal.jsonl'
            def rows(items):
                p.write_text('\n'.join(json.dumps(x) for x in items)+'\n');p.chmod(0o600)
            rows([dict(registration,series_ticker='OTHER'),end])
            with self.assertRaisesRegex(ValueError,'registration'):
                load_validated_rows(p)
            rows([registration,end,event])
            with self.assertRaisesRegex(ValueError,'after original study end'):
                load_validated_rows(p)
            rows([registration,event,end])
            with self.assertRaisesRegex(ValueError,'window'):
                load_validated_rows(p)


if __name__ == '__main__':
    unittest.main()
