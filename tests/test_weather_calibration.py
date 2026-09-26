"""Synthetic data tests; never use these cases as evidence of profitability."""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch
from decimal import Decimal

from weather_calibration import asof_gfs, official_nyc, wilson_lower, event_probability, calibration, evaluate_archive


class CalibrationTests(unittest.TestCase):
    def test_fixed_run_is_previous_day_12utc_not_hindsight(self):
        observed = {}
        def get(url, params):
            observed.update(params)
            times = [f'2026-09-25T{h:02}:00' for h in range(24)]
            return {'timezone':'America/New_York','latitude':40.7833,'longitude':-73.9667,
                    'hourly':{'time':times,'temperature_2m':[65.5]*23+[72.2]}}
        high, run = asof_gfs(date(2026,9,25), get)
        self.assertEqual((high, run),(72.2,'2026-09-24T12:00'))
        self.assertEqual(observed['run'],run)
        self.assertEqual(observed['models'],'gfs_global')

    def test_reject_partial_hourly_forecast(self):
        with self.assertRaisesRegex(ValueError,'hours'):
            asof_gfs(date(2026,9,25),lambda u,p:{'timezone':'America/New_York',
                'latitude':40.7833,'longitude':-73.9667,
                'hourly':{'time':['2026-09-25T12:00'],'temperature_2m':[70]}})

    def test_official_revised_and_other_station_rejected(self):
        day=date(2026,9,25)
        base={'date':day.isoformat(),'results':[{'station':{'cliId':'NYC','icao':'KNYC',
              'timezone':'America/New_York','city':'New York City'},'status':'official',
              'data':{'isOfficial':True,'reportDate':day.isoformat(),'maxTemp':70}}]}
        self.assertEqual(official_nyc(day,lambda u,p:base),70)
        base['results'][0]['status']='revised'
        with self.assertRaisesRegex(ValueError,'untrusted'):
            official_nyc(day,lambda u,p:base)
        base['results'][0]['status']='official';base['results'][0]['station']['cliId']='BOS'
        with self.assertRaisesRegex(ValueError,'Ambiguous'):
            official_nyc(day,lambda u,p:base)

    def test_wilson_bound_never_confuses_one_hit_with_certainty(self):
        self.assertLess(wilson_lower(1,1),.3)
        self.assertLess(wilson_lower(80,100),.75)
        with self.assertRaises(ValueError):wilson_lower(0,0)
        rule='If the maximum temperature recorded at New York City (CLINYC) for Sep 27, 2026, is between 64-65° fahrenheit according to The Weather Company, then the market resolves to Yes.'
        mean,lower=event_probability(65,[0]*80,rule)
        self.assertLess(lower,mean)
        self.assertGreater(mean,.98)

    def test_train_and_holdout_separate_and_no_quote_is_not_candidate(self):
        from datetime import timedelta
        start=date(2026,6,1)
        rows=[]
        for i in range(90):
            d=start+timedelta(days=i)
            rows.append({'date':d.isoformat(),'error_station_minus_grid_f':0.0,
                         'grid_forecast_max_f':65.,'official_station_max_f':65})
        # Chronological split: 65 train and 25 validation, never train on holdout.
        rule='If the maximum temperature recorded at New York City (CLINYC) for Sep 27, 2026, is between 64-65° fahrenheit according to The Weather Company, then the market resolves to Yes.'
        market={'ticker':'KXHIGHNY-26SEP27-B65','rules_primary':rule}
        client=Mock();client.get_orderbook.return_value={'yes_dollars':[],'no_dollars':[]}
        value=calibration(rows,start+timedelta(days=64),[market],65.,('quadratic',Decimal('1')),client)
        self.assertEqual((value['training_days'],value['holdout_days']),(65,25))
        self.assertEqual((value['within_5f_train_days'],value['within_5f_holdout_days']),(65,25))
        self.assertIsNone(value['predictions'][0]['fee_inclusive_hurdle'])
        self.assertFalse(value['predictions'][0]['provisional_hypothesis_only'])
        extrapolated=calibration(rows,start+timedelta(days=64),[market],55.,('quadratic',Decimal('1')),client)
        self.assertEqual((extrapolated['within_5f_train_days'],extrapolated['within_5f_holdout_days']),(0,0))
        self.assertFalse(extrapolated['supported_forecast_regime'])
        self.assertIsNone(extrapolated['predictions'][0]['model_probability'])
        self.assertIsNone(extrapolated['predictions'][0]['wilson_lower_95'])
        self.assertIsNone(extrapolated['predictions'][0]['holdout_brier_model'])
        self.assertFalse(extrapolated['predictions'][0]['provisional_hypothesis_only'])

    def test_local_residuals_not_all_season_errors_determine_probability(self):
        from datetime import timedelta
        start=date(2026,6,1);rows=[]
        for i in range(110):
            day=start+timedelta(days=i)
            nearby = 60 <= i < 85 or i >= 85
            forecast,station=(64.,62) if nearby else (80.,95)
            rows.append({'date':day.isoformat(),'error_station_minus_grid_f':station-forecast,
                         'grid_forecast_max_f':forecast,'official_station_max_f':station})
        rule='If the maximum temperature recorded at New York City (CLINYC) for Sep 27, 2026, is less than 65° fahrenheit according to The Weather Company, then the market resolves to Yes.'
        market={'ticker':'KXHIGHNY-26SEP27-T65','rules_primary':rule}
        client=Mock();client.get_orderbook.return_value={'yes_dollars':[],'no_dollars':[]}
        result=calibration(rows,start+timedelta(days=84),[market],64.,('quadratic',Decimal('1')),client)
        self.assertEqual((result['within_5f_train_days'],result['within_5f_holdout_days']),(25,25))
        self.assertTrue(result['supported_forecast_regime'])
        self.assertEqual(result['predictions'][0]['holdout_scored_days'],25)
        self.assertGreater(result['predictions'][0]['model_probability'],.95)
        self.assertLess(event_probability(64.,[r['error_station_minus_grid_f'] for r in rows[:85]],rule)[0],.4)
        self.assertIsNotNone(result['predictions'][0]['holdout_brier_model'])

    def test_wrong_binding_station_aborts_before_nyc_label_or_forecast(self):
        from datetime import timedelta
        start=date(2026,6,1);end=start+timedelta(days=89)
        rows=[{'date':(start+timedelta(days=i)).isoformat(),
               'model_run_utc':(start+timedelta(days=i-1)).isoformat()+'T12:00Z',
               'forecast_origin':'https://single-runs-api.open-meteo.com/v1/forecast',
               'settlement_report_origin':'https://weather.com/kalshi/api/climate/primary',
               'official_station_max_f':65} for i in range(90)]
        payload={'train_start':start.isoformat(),'train_end':(start+timedelta(days=64)).isoformat(),
                 'holdout_end':end.isoformat(),'target':'2026-09-27',
                 'archived_observations':rows,'missing_or_untrusted_dates':[],
                 'orders':0,'fills':0,'live_strategy_authorized':False}
        wrong='If the maximum temperature recorded at Boston (CLIBOS) for Sep 27, 2026, is less than 65° fahrenheit according to The Weather Company, then the market resolves to Yes.'
        client=Mock();client.get_event.return_value={'markets':[{'ticker':'KXHIGHNY-26SEP27-T65',
            'status':'active','rules_primary':wrong}],'series_ticker':'KXHIGHNY'}
        with patch('weather_calibration.PublicMarketClient',return_value=client),\
             patch('weather_calibration.asof_gfs',side_effect=AssertionError('no forecast permitted')):
            with self.assertRaisesRegex(ValueError,'NYC CLI station'):
                evaluate_archive(payload)
        client.get_event.assert_called_once()
        client.get_series.assert_not_called()
        client.get_orderbook.assert_not_called()
        self.assertNotIn('evaluation',payload)

    def test_missing_archive_day_cannot_produce_positive_screen(self):
        from datetime import timedelta
        start=date(2026,6,1);end=start+timedelta(days=89)
        rows=[]
        for i in range(90):
            day=start+timedelta(days=i)
            if i == 5:continue
            rows.append({'date':day.isoformat(),'model_run_utc':(day-timedelta(days=1)).isoformat()+'T12:00Z',
                'forecast_origin':'https://single-runs-api.open-meteo.com/v1/forecast',
                'settlement_report_origin':'https://weather.com/kalshi/api/climate/primary',
                'official_station_max_f':65})
        payload={'train_start':start.isoformat(),'train_end':(start+timedelta(days=64)).isoformat(),
            'holdout_end':end.isoformat(),'target':(end+timedelta(days=2)).isoformat(),
            'archived_observations':rows,'missing_or_untrusted_dates':[{'date':(start+timedelta(days=5)).isoformat(),'reason':'HTTPError'}],
            'orders':0,'fills':0,'live_strategy_authorized':False}
        model={'training_days':64,'holdout_days':25,'predictions':[{'provisional_hypothesis_only':True}]}
        client=Mock();client.get_event.return_value={'markets':[],'series_ticker':'KXHIGHNY'}
        client.get_series.return_value={'settlement_sources':[]}
        with patch('weather_calibration.asof_gfs',return_value=(65.,'2026-08-29T12:00')),\
             patch('weather_calibration.PublicMarketClient',return_value=client),\
             patch('weather_calibration.rule_identity',return_value=('New York City','CLINYC')),\
             patch('weather_forward.require_source'),\
             patch('weather_calibration.effective_fees',return_value=('quadratic',Decimal('1'))),\
             patch('weather_calibration.calibration',return_value=model):
            evaluated=evaluate_archive(payload)
        self.assertTrue(evaluated['evaluation']['incomplete_source_days'])
        self.assertFalse(evaluated['evaluation']['predictions'][0]['provisional_hypothesis_only'])


if __name__=='__main__': unittest.main()
