"""No-network weather forward-study regressions; synthetic fixtures are NOT performance data."""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import weather_forward as study
from core.public_market import MarketDataError


class IdentityTests(unittest.TestCase):
    def test_market_rules_require_one_source_station_and_date(self):
        rule = ('If the maximum temperature recorded at New York City (CLINYC) for '
                'Sep 27, 2026, is between 67-68° fahrenheit according to The Weather Company, '
                'then the market resolves to Yes.')
        markets = [{'ticker': 'one', 'status': 'active', 'rules_primary': rule},
                   {'ticker': 'two', 'status': 'active', 'rules_primary': rule}]
        self.assertEqual(study.rule_identity(markets, date(2026, 9, 27)),
                         ('New York City', 'CLINYC'))
        with self.assertRaisesRegex(MarketDataError, 'target date'):
            study.rule_identity(markets, date(2026, 9, 28))
        markets[1]['rules_primary'] = rule.replace('CLINYC', 'CLIBOS')
        with self.assertRaisesRegex(MarketDataError, 'inconsistent'):
            study.rule_identity(markets, date(2026, 9, 27))

    def test_station_mapping_requires_prior_final_report(self):
        row = {'station': {'cliId':'NYC','city':'New York City','timezone':'America/New_York','icao':'KNYC'},
               'data':{'isOfficial':True,'reportDate':'2026-09-25'},'status':'official'}
        session = Mock()
        with patch.object(study,'get_json',return_value={'date':'2026-09-25','results':[row]}) as get:
            station,_=study.portal_station(session,'New York City','CLINYC',date(2026,9,27))
            self.assertEqual(station['icao'],'KNYC')
            self.assertEqual(get.call_args.kwargs['params'],{'date':'2026-09-25'})
        row['status']='preliminary'
        with patch.object(study,'get_json',return_value={'date':'2026-09-25','results':[row]}):
            with self.assertRaisesRegex(MarketDataError,'not final'):
                study.portal_station(session,'New York City','CLINYC',date(2026,9,27))

    def test_dst_aware_hourly_forecast_complete_and_generated_before_decision(self):
        now=datetime(2026,9,26,22,0,tzinfo=timezone.utc)
        start=datetime(2026,9,27,4,0,tzinfo=timezone.utc)
        hourly=[{'startTime':study.stamp(start+timedelta(hours=i)),
                 'temperature':67+i%6,'temperatureUnit':'F'} for i in range(24)]
        station={'properties':{'stationIdentifier':'KNYC'},
                 'geometry':{'type':'Point','coordinates':[-73.97,40.78]}}
        points={'properties':{'forecastHourly':'https://api.weather.gov/gridpoints/OKX/34,45/forecast/hourly'}}
        forecast={'properties':{'generatedAt':'2026-09-26T21:00:00Z','periods':hourly}}
        with patch.object(study,'get_json',side_effect=[station,points,forecast]):
            result=study.nws_forecast(Mock(),{'icao':'KNYC'},date(2026,9,27),now)
        self.assertEqual(result['hourly_count'],24)
        self.assertIn('not a TWC',result['interpretation'])
        with patch.object(study,'get_json',side_effect=[station,points,{'properties':{
                'generatedAt':'2026-09-26T21:00:00Z','periods':hourly[:-1]}}]):
            with self.assertRaisesRegex(MarketDataError,'Incomplete'):
                study.nws_forecast(Mock(),{'icao':'KNYC'},date(2026,9,27),now)

    def test_final_label_needs_matching_venue_settlement(self):
        observed = {'target_date':'2026-09-25','event_ticker':'KXHIGHNY-26SEP25',
                    'station_from_prior_final_TWC_report':{'cliId':'NYC','icao':'KNYC'},
                    'markets':[{'ticker':'A'}]}
        climate={'date':'2026-09-25','results':[{'station':{'cliId':'NYC','icao':'KNYC'},
                 'status':'official','data':{'isOfficial':True,'reportDate':'2026-09-25','maxTemp':69}}]}
        venue=Mock();venue.get_event.return_value={'markets':[{'ticker':'A','status':'active'}]}
        with patch.object(study,'get_json',return_value=climate):
            self.assertIsNone(study.label(venue,Mock(),observed))
            venue.get_event.return_value={'markets':[{'ticker':'A','status':'settled',
                    'settlement_value_dollars':'1.0000','result':'yes'}]}
            result=study.label(venue,Mock(),observed)
        self.assertEqual(result['twc_station_row']['data']['maxTemp'],69)
        self.assertEqual(result['venue_settlements'][0]['result'],'yes')
        self.assertEqual(result['real_orders'],0)

    def test_registration_recovery_and_locking_never_backfill(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'logs';folder.mkdir(mode=0o700)
            journal=folder/'weather.jsonl'
            start=datetime(2026,9,26,21,0,tzinfo=timezone.utc)
            later=datetime(2026,10,5,22,6,tzinfo=timezone.utc)
            times=iter([start,later,later,later])
            result=study.run(journal=journal,now_fn=lambda: next(times),
                             public=Mock(),twc=Mock(),nws=Mock(),sleep=lambda _:None)
            self.assertEqual(result['real_orders'],0)
            rows=[json.loads(x) for x in journal.read_text().splitlines()]
            self.assertEqual(rows[0]['type'],'study_start')
            self.assertEqual(rows[-1]['type'],'study_end')
            self.assertTrue(all(x.get('real_orders')==0 and x.get('paper_orders')==0 for x in rows))
            self.assertEqual(study.run(journal=journal,public=Mock(),twc=Mock(),nws=Mock())['already_finished'],True)
            self.assertEqual(len(journal.read_text().splitlines()),2)

    def test_journal_rejects_duplicate_daily_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'weather.jsonl'
            start={'type':'study_start','series':study.SERIES,'first_target':study.FIRST_TARGET.isoformat(),
                   'last_target':study.LAST_TARGET.isoformat(),'until_utc':study.stamp(study.DEADLINE),
                   'cutoff_local':'18:00 America/New_York','paper_orders':0,'real_orders':0,'real_fills':0}
            row={'type':'decision_error','target_date':'2026-09-27','paper_orders':0,'real_orders':0,'real_fills':0}
            p.write_text('\n'.join(json.dumps(x) for x in [start,row,row])+'\n');p.chmod(0o600)
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                study.load_journal(p)


if __name__=='__main__':
    unittest.main()
