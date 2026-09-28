"""Offline report replay tests: never infer fills, wins, or actual profit."""
import json
import unittest
from copy import deepcopy
from decimal import Decimal
from report_mlb_f3_partitions import render
from tests.test_scan_mlb_f3_partitions import example,books,scored


def journal(*,positive=False,cycles=1,unknown=False):
    event,series=example();totals={'cycles':0,'events':0,'valid_books':0,
     'positive_indicative':0,'ineligible':0,'liquidity_unavailable':0,
     'source_errors':0,'cycle_errors':0,'orders':0,'fills':0}
    if unknown:
        for m in event['markets']:m.pop('is_provisional')
    rows=[]
    for i in range(cycles):
        start=f'2026-09-27T02:{i+1:02}:00Z';end=f'2026-09-27T02:{i+1:02}:02Z'
        b=books()
        if positive:
            for ticker,price in zip(b,('.43','.44','.45')):
                b[ticker]['yes_dollars']=[[price,'3.00']]
            # Three NO contracts cost less than their conditional $2 payout.
            for ticker,price in zip(b,('.60','.70','.70')):
                b[ticker]['no_dollars']=[[str(Decimal('1')-Decimal(price)),'4.00']]
        quote=scored(event,series,b,started=start,completed=end)
        quote.update({'type':'partition_quote','cycle_number':i+1,
            'observed_utc':end,'orders':0,'fills':0})
        rows.append(quote)
        totals['cycles']+=1;totals['events']+=1;totals['valid_books']+=1
        totals['positive_indicative']+=int(quote['indicative_only_nonatomic_candidate'])
        rows.append({'type':'partition_cycle','schema_version':2,'cycle_number':i+1,
           'started_utc':start,'observed_utc':end,'status':'complete','totals':totals.copy(),
           'orders':0,'fills':0})
    rows.append({'type':'partition_end','schema_version':2,
        'observed_utc':f'2026-09-27T02:{cycles:02}:03Z',
        'totals':totals.copy(),'orders':0,'fills':0,'not_profit_evidence':True})
    return rows


def render_rows(rows):
    return render([json.dumps(r) for r in rows])


class PartitionReportTests(unittest.TestCase):
    def test_repeated_event_is_not_independent_and_provisional_unsupported(self):
        rows=journal(cycles=2)
        text=render_rows(rows)
        self.assertIn('independent events with a displayed book: **1**',text)
        self.assertIn('event/book snapshots: **2**',text)
        self.assertIn('**0** book snapshots lacked an explicit',text)
        self.assertIn('No win percentage or profit claim',text)

    def test_positive_price_anomaly_without_provisional_status_not_promoted(self):
        rows=journal(positive=True,unknown=True)
        q=rows[0]
        self.assertTrue(q['baskets']['no']['price_anomaly_after_costs'])
        self.assertFalse(q['indicative_only_nonatomic_candidate'])
        self.assertIn('**1** book snapshots lacked an explicit',render_rows(rows))

    def test_verified_positive_quote_is_still_nonautomic(self):
        rows=journal(positive=True)
        q=rows[0]
        for key in ('raw_event','raw_post_event'):
            for m in q[key]['markets']:m['is_provisional']=False
        # Recompute a new genuine quote, not merely flip its boolean.
        from scan_mlb_f3_partitions import screen_event
        replacement=screen_event(q['raw_event'],q['raw_series'],q['raw_orderbooks_fp'],
            started=q['books_started_utc'],completed=q['books_completed_utc'],
            book_read_order=q['book_read_order'],book_receipts=q['book_receipts_utc'],
            post_event=q['raw_post_event'],post_series=q['raw_post_series'])
        replacement.update({'type':'partition_quote','cycle_number':1,
            'observed_utc':q['observed_utc'],'orders':0,'fills':0})
        rows[0]=replacement
        rows[1]['totals']['positive_indicative']=1
        rows[2]['totals']['positive_indicative']=1
        text=render_rows(rows)
        self.assertIn('Positive *indicative non-atomic* basket snapshots: **1**',text)
        self.assertIn('non-atomic, not traded',text)

    def test_tampered_fee_books_or_rule_does_not_generate_a_valid_report(self):
        for field,changed in (('one_set_fee_and_buffer_net_dollars','9.99'),
                              ('one_set_gross_dollars','9.99')):
            rows=journal();rows[0]['baskets']['yes'][field]=changed
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'differs from raw'):
                render_rows(rows)
        rows=journal();rows[0]['raw_orderbooks_fp'].pop(next(iter(rows[0]['raw_orderbooks_fp'])))
        with self.assertRaises(Exception):render_rows(rows)
        rows=journal();rows[0]['raw_post_event']['markets'][0]['rules_primary']+=' changed'
        with self.assertRaises(Exception):render_rows(rows)

    def test_missing_end_or_legacy_journal_and_counter_fraud_rejected(self):
        rows=journal();rows.pop()
        with self.assertRaisesRegex(ValueError,'terminal'):
            render_rows(rows)
        rows=journal();rows[0]['schema_version']=1
        with self.assertRaisesRegex(ValueError,'Unversioned'):
            render_rows(rows)
        rows=journal();rows[1]['totals']['events']=2
        with self.assertRaisesRegex(ValueError,'counters'):
            render_rows(rows)
        rows=journal();rows[0]['orders']=1
        with self.assertRaisesRegex(ValueError,'execution-bearing'):
            render_rows(rows)

    def test_source_error_is_not_ineligible(self):
        rows=journal();err={'type':'partition_source_error','schema_version':2,
           'cycle_number':1,'observed_utc':'2026-09-27T02:01:01Z',
           'event_ticker':'KXMLBF3-OTHER','reason':'SSLError','orders':0,'fills':0}
        rows.insert(1,err)
        for record in rows[2:]:
            record['totals']['events']+=1
            record['totals']['source_errors']+=1
        self.assertIn('**1** venue/source errors',render_rows(rows))


if __name__=='__main__':unittest.main()
