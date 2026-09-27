"""Synthetic contract and book tests; positive quote is never a fill or profit."""
from __future__ import annotations

import json
import tempfile
import unittest
import requests
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from core.public_market import MarketDataError
from scan_mlb_f3_partitions import one_unit_ask, one_unit_yes_ask, run, scan_cycle, scan_one, screen_event, strict_rules

EID='KXMLBF3-26SEP271507CINTOR'
WHO='Cincinnati vs Toronto professional baseball game originally scheduled for Sep 27, 2026 at 3:07 PM EDT'
BRAND=('Kalshi is not affiliated, associated, authorized, endorsed by, or in any way officially '
       'connected with the Governing League. All trademarks, logos, and brand names are the '
       'property of their respective owners.')
SECONDARY=(f'This market refers to the first 3 innings of the {WHO}. If the score at the end of the first 3 innings '
           'is tied, the "Tie" strike will resolve to Yes and all team strikes will resolve to No. '
           'If this game is postponed or delayed, the market will remain open and close after the '
           'rescheduled game has finished (within two days).\n\n'+BRAND)


def example():
    markets=[]
    for suffix, rule, title in [
        ('CIN',f'If Cincinnati wins the first 3 innings of the {WHO}, then the market resolves to Yes.','Cincinnati wins first 3 innings'),
        ('TOR',f'If Toronto wins the first 3 innings of the {WHO}, then the market resolves to Yes.','Toronto wins first 3 innings'),
        ('TIE',f'If Cincinnati and Toronto tie in the first 3 innings of the {WHO}, then the market resolves to Yes.','Tie first 3 innings')]:
        markets.append({'ticker':EID+'-'+suffix,'event_ticker':EID,'exchange_index':3,'status':'active',
          'is_provisional':False,'market_type':'binary','notional_value_dollars':'1.0000',
          'updated_time':'2026-09-27T02:00:00Z','price_level_structure':'linear_cent',
          'price_ranges':[{'start':'0.0000','end':'1.0000','step':'0.0100'}],
          'can_close_early':True,'early_close_condition':'This market will close and expire after a winner is declared.',
          'expected_expiration_time':'2030-09-27T22:07:00Z','close_time':'2030-09-30T19:07:00Z',
          'rules_primary':rule,'rules_secondary':SECONDARY,'yes_sub_title':title})
    event={'event_ticker':EID,'series_ticker':'KXMLBF3','mutually_exclusive':True,
           'collateral_return_type':'MECNET','exchange_index':3,'markets':markets}
    series={'ticker':'KXMLBF3','fee_type':'quadratic','fee_multiplier':0.5}
    return event,series


def books(asks=(Decimal('0.25'),Decimal('0.30'),Decimal('0.35'))):
    return {EID+'-'+x:{'yes_dollars':[['0.08','5.00']],
                        'no_dollars':[[str(Decimal('1')-p),'4.00']]}
            for x,p in zip(('CIN','TOR','TIE'),asks)}


def scored(event,series,b,*,started='2026-09-27T02:01:00Z',completed='2026-09-27T02:01:02Z'):
    order=list(b)
    base=datetime.fromisoformat(started.replace('Z','+00:00'))
    receipts={ticker:(base+timedelta(milliseconds=i*100)).isoformat().replace('+00:00','Z')
              for i,ticker in enumerate(order,1)}
    return screen_event(event,series,b,started=started,completed=completed,
        post_event=deepcopy(event),post_series=deepcopy(series),
        book_read_order=order,book_receipts=receipts)


class ThreeWayTests(unittest.TestCase):
    def test_three_distinct_outcomes_and_exact_secondary(self):
        e,_=example()
        self.assertEqual(len(strict_rules(e,e['markets'])),64)
        e['markets'][0]['rules_secondary']+=' In some cases we pay fifty cents.'
        with self.assertRaisesRegex(MarketDataError,'secondary'):
            strict_rules(e,e['markets'])

    def test_mutual_exclusivity_is_not_exhaustiveness(self):
        e,_=example();e['markets']=e['markets'][:2]
        with self.assertRaisesRegex(MarketDataError,'partition'):
            strict_rules(e,e['markets'])
        e,_=example();e['markets'][1]['rules_primary']=e['markets'][0]['rules_primary']
        with self.assertRaisesRegex(MarketDataError,'duplicate'):
            strict_rules(e,e['markets'])

    def test_invalid_event_metadata_and_void_or_tie_exception_rejected(self):
        for change in ({'collateral_return_type':'OTHER'}, {'mutually_exclusive':False}, {'exchange_index':2}):
            e,_=example();e.update(change)
            with self.subTest(change=change),self.assertRaises(MarketDataError):
                strict_rules(e,e['markets'])
        e,_=example();e['markets'][2]['notional_value_dollars']='0.5000'
        with self.assertRaises(MarketDataError):strict_rules(e,e['markets'])
        e,_=example();e['markets'][2]['rules_primary']=e['markets'][2]['rules_primary'].replace('resolves to Yes','resolves at fair value')
        with self.assertRaises(MarketDataError):strict_rules(e,e['markets'])

    def test_best_ask_requires_one_share_and_both_book_sides(self):
        e,_=example();m=e['markets'][0]
        b={'yes_dollars':[['0.10','2.00']],'no_dollars':[['0.70','0.80'],['0.69','20.00']]}
        with self.assertRaisesRegex(MarketDataError,'best YES ask'):
            one_unit_yes_ask(m,b)
        b['no_dollars'][0][1]='1.00'
        self.assertEqual(one_unit_yes_ask(m,b)[0],Decimal('0.30'))
        self.assertEqual(one_unit_ask(m,b,'no')[0],Decimal('0.90'))
        b['yes_dollars']=[]
        with self.assertRaisesRegex(MarketDataError,'One-sided'):
            one_unit_yes_ask(m,b)

    def test_one_set_all_leg_net_and_nonatomic_label(self):
        e,s=example();start='2026-09-27T02:01:00Z';end='2026-09-27T02:01:02Z'
        r=scored(e,s,books(),started=start,completed=end)
        self.assertEqual(r['baskets']['yes']['one_set_gross_dollars'],'0.10')
        self.assertEqual(r['baskets']['no']['conditional_scored_game_payout_dollars'],'2')
        self.assertEqual(r['orders'],0)
        self.assertEqual(r['fills'],0)
        self.assertTrue(r['not_a_locked_profit'])
        self.assertTrue(r['indicative_only_nonatomic_candidate'])
        self.assertEqual(len(r['baskets']['yes']['legs']),3)
        expensive=scored(e,s,books((Decimal('.33'),Decimal('.47'),Decimal('.24'))),started=start,completed=end)
        self.assertEqual(expensive['baskets']['yes']['one_set_gross_dollars'],'-0.04')
        self.assertFalse(expensive['indicative_only_nonatomic_candidate'])
        self.assertLess(Decimal(expensive['baskets']['yes']['one_set_fee_and_buffer_net_dollars']),Decimal('-0.04'))

    def test_three_no_contracts_pay_two_only_after_exactly_one_yes(self):
        e,s=example();b=books((Decimal('.60'),Decimal('.70'),Decimal('.70')))
        for ticker,price in zip((EID+'-CIN',EID+'-TOR',EID+'-TIE'),('.43','.44','.45')):
            b[ticker]['yes_dollars']=[[price,'3.00']]
        r=scored(e,s,b)
        self.assertEqual(r['baskets']['no']['one_set_gross_dollars'],'0.32')
        self.assertFalse(r['baskets']['yes']['indicative_only_nonatomic_candidate'])
        self.assertTrue(r['baskets']['no']['indicative_only_nonatomic_candidate'])
        self.assertTrue(r['not_a_locked_profit'])

    def test_stale_or_incomplete_three_book_set_fails(self):
        e,s=example();b=books();b.pop(EID+'-TOR')
        with self.assertRaisesRegex(MarketDataError,'Incomplete'):
            scored(e,s,b)
        with self.assertRaisesRegex(MarketDataError,'fresh'):
            scored(e,s,books(),completed='2026-09-27T02:01:12Z')

    def test_unknown_provisional_suppresses_positive_quote(self):
        e,s=example()
        for m in e['markets']:m.pop('is_provisional')
        r=scored(e,s,books())
        self.assertTrue(r['baskets']['yes']['price_anomaly_after_costs'])
        self.assertFalse(r['baskets']['yes']['indicative_only_nonatomic_candidate'])
        self.assertFalse(r['provisional_status_verified'])
        e,s=example();e['markets'][0]['is_provisional']='true'
        with self.assertRaisesRegex(MarketDataError,'Provisional'):
            scored(e,s,books())

    def test_rule_fee_or_market_update_change_after_books_aborts(self):
        e,s=example();post=deepcopy(e)
        post['markets'][0]['updated_time']='2026-09-27T02:00:30Z'
        receipt={ticker:f'2026-09-27T02:01:00.{i}Z' for i,ticker in enumerate(books(),1)}
        with self.assertRaisesRegex(MarketDataError,'changed after books'):
            screen_event(e,s,books(),started='2026-09-27T02:01:00Z',completed='2026-09-27T02:01:02Z',
                book_read_order=list(books()),book_receipts=receipt,post_event=post,post_series=s)

    def test_network_tls_failure_is_not_ineligible_or_no_opportunity(self):
        client=Mock();client.get_event.side_effect=requests.exceptions.SSLError('certificate failure')
        with patch('scan_mlb_f3_partitions.PublicMarketClient',return_value=client):
            result=scan_one(EID,{EID+'-CIN'},Decimal('0.03'))
        self.assertEqual(result['type'],'partition_source_error')
        self.assertEqual(result['reason'],'SSLError')
        client.get_series.assert_not_called()
        client.get_orderbook.assert_not_called()

    def test_cycle_failure_never_becomes_zero_opportunity_and_journal_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'data.jsonl'
            with patch('scan_mlb_f3_partitions.scan_cycle',side_effect=MarketDataError('API unavailable')):
                result=run(output=p,cycles=1,interval=15,max_events=3,workers=2)
            records=[json.loads(s) for s in p.read_text().splitlines()]
            self.assertEqual(result['cycle_errors'],1)
            self.assertEqual(records[0]['type'],'cycle_error')
            self.assertEqual(records[-1]['orders'],0)
            with self.assertRaises(FileExistsError):
                run(output=p,cycles=1,interval=15,max_events=3,workers=2)


if __name__=='__main__':unittest.main()
