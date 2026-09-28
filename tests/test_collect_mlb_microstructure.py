"""No-network collector tests; synthetic fixtures do not count as market evidence."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from collect_mlb_microstructure import collect, discover, emit, event_markets, load_journal, open_private_journal, scan_selected
from core.public_market import MarketDataError
from tests.test_microstructure import market, book, RULE


class MLBCollectorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'private' / 'forward.jsonl'
        self.client = Mock()
        self.series = {'ticker': 'KXMLBGAME', 'fee_type': 'quadratic_with_maker_fees', 'fee_multiplier': 0.5}
        self.event = {'event_ticker': 'X', 'series_ticker': 'KXMLBGAME', 'category': 'Sports',
                      'mutually_exclusive': True, 'product_metadata': {'competition_scope': 'Game'},
                      'markets': [market('X-A'), market('X-B')]}
        self.client.get_markets.return_value = [{'event_ticker': 'X'}]
        self.client.get_event.return_value = self.event
        self.client.get_orderbook.side_effect = [book(), book(yes='0.45', no='0.53')]

    def test_selection_archives_rules_and_snapshot_without_orders(self):
        with open_private_journal(self.path) as file:
            selected = discover(self.client, file, datetime(2026, 9, 25, tzinfo=timezone.utc), {}, self.series)
            self.assertEqual(selected, {'X': '2026-09-26T23:15:00Z'})
            scanned = scan_selected(self.client, file, selected, self.series,
                                    datetime(2026, 9, 26, 22, 45, tzinfo=timezone.utc))
        self.assertEqual(scanned, 1)
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual([r['type'] for r in rows], ['event_selected', 'book_snapshot'])
        self.assertEqual(rows[0]['rules'][0]['rules_primary'], RULE)
        self.assertEqual(rows[1]['fee_multiplier'], 0.5)
        self.assertEqual(rows[1]['conditional_quote']['conditional_paired_mark_dollars'], '0.00')
        self.assertEqual(rows[1]['real_orders'], 0)
        self.assertEqual(self.client.get_orderbook.call_count, 2)
        self.assertTrue(all(x.kwargs['depth'] == 1 for x in self.client.get_orderbook.call_args_list))

    def test_finalized_market_is_ineligible_without_book_requests(self):
        self.event['markets'][1]['status'] = 'finalized'
        with open_private_journal(self.path) as file:
            result = scan_selected(self.client, file, {'X': '2026-09-26T23:15:00Z'}, self.series,
                                   datetime(2026, 9, 26, 22, 45, tzinfo=timezone.utc))
        self.assertEqual(result, 0)
        self.client.get_orderbook.assert_not_called()
        row = json.loads(self.path.read_text().splitlines()[0])
        self.assertEqual(row['type'], 'book_ineligible')
        self.assertEqual(row['statuses'], ['active', 'finalized'])
        self.assertEqual(row['real_orders'], 0)

    def test_event_with_extra_markets_and_ambiguous_time_excluded(self):
        self.event['markets'].append(market('X-C'))
        with self.assertRaises(MarketDataError): event_markets(self.event)
        with open_private_journal(self.path) as file:
            selected = discover(self.client, file, datetime(2026, 9, 25, tzinfo=timezone.utc), {}, self.series)
        self.assertFalse(selected)
        self.assertIn('event_excluded', self.path.read_text())

    def test_late_discovery_rejected_despite_old_study_registration(self):
        # Study registered yesterday, but this is the FIRST sighting of a
        # 23:15 UTC game. A 22:50 discovery has only 25 minutes of lead time.
        with open_private_journal(self.path) as file:
            selected = discover(self.client, file, datetime(2026, 9, 26, 22, 50, tzinfo=timezone.utc), {}, self.series)
        self.assertEqual(selected, {})

    def test_insecure_file_or_symlink_fails(self):
        self.path.parent.mkdir(mode=0o700)
        self.path.write_text('{}\n')
        os.chmod(self.path, 0o644)
        with self.assertRaises(PermissionError): load_journal(self.path)
        self.path.unlink()
        self.path.symlink_to('/dev/null')
        with self.assertRaises(PermissionError): open_private_journal(self.path)

    def test_persisted_cohort_cannot_precede_study_registration(self):
        with open_private_journal(self.path) as output:
            output.write(json.dumps({'type': 'event_selected', 'event_ticker': 'OLD',
                                     'scheduled_start_utc': '2026-09-26T23:15:00Z'}) + '\n')
        with self.assertRaisesRegex(ValueError, 'First journal row'):
            load_journal(self.path)

    def test_completed_study_does_not_append_second_end(self):
        registration = {'type': 'study_start', 'start_at_utc': '2026-09-26T07:00:00Z',
                        'until_utc': '2026-09-27T07:00:00Z', 'series_ticker': 'KXMLBGAME',
                        'max_events': 120, 'order_writes_enabled': False}
        with open_private_journal(self.path) as output:
            output.write(json.dumps(registration) + '\n')
            output.write(json.dumps({'type': 'study_end', 'real_orders': 0}) + '\n')
        original = self.path.read_text()
        result = collect(until=datetime(2026, 9, 27, 7, tzinfo=timezone.utc),
                         journal=self.path, client=self.client, sleep=lambda _: None)
        self.assertTrue(result['already_completed'])
        self.assertEqual(self.path.read_text(), original)
        self.client.get_series.assert_not_called()

    def test_expired_new_study_rejects_before_journal_or_client_calls(self):
        now=datetime(2026,9,26,7,tzinfo=timezone.utc)
        with patch('collect_mlb_microstructure.now_utc',return_value=now):
            with self.assertRaisesRegex(ValueError,'future'):
                collect(until=now,journal=self.path,client=self.client,sleep=lambda _:None)
        self.assertFalse(self.path.exists())
        self.client.get_series.assert_not_called()

    def test_emit_fsyncs_and_only_truncated_final_line_is_recovered(self):
        registration={'type':'study_start','start_at_utc':'2026-09-26T07:00:00Z',
                      'until_utc':'2026-09-27T07:00:00Z','series_ticker':'KXMLBGAME',
                      'max_events':120,'order_writes_enabled':False}
        with open_private_journal(self.path) as output, patch('collect_mlb_microstructure.os.fsync') as sync:
            emit(output,'study_start',start_at_utc=registration['start_at_utc'],until_utc=registration['until_utc'],
                 series_ticker='KXMLBGAME',max_events=120,order_writes_enabled=False)
            self.assertTrue(sync.called)
        with self.path.open('ab') as output:
            output.write(b'{"type":"event_selected"')
        with open_private_journal(self.path):
            pass
        self.assertEqual(load_journal(self.path)[0][0]['type'],'study_start')
        self.path.write_text(json.dumps(registration)+'\n{not-json}\n')
        self.path.chmod(0o600)
        with self.assertRaisesRegex(ValueError,'interior-corrupt'):
            load_journal(self.path)


if __name__ == '__main__':
    unittest.main()
