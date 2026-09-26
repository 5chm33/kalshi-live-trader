"""Public-series inventory fixtures, not forecasts or outcomes."""
import unittest
from unittest.mock import Mock
from audit_weather_sources import inventory
from core.public_market import MarketDataError


class WeatherSourcesTests(unittest.TestCase):
    def test_nws_and_twc_remain_separate(self):
        client = Mock()
        client._get.return_value = {'series': [
            {'ticker': 'A', 'frequency': 'daily', 'title': 'Highest temperature in A',
             'settlement_sources': [{'name': 'The Weather Company'}]},
            {'ticker': 'B', 'frequency': 'daily', 'title': 'Lowest temperature in B',
             'settlement_sources': [{'name': 'National Weather Service'}]},
            {'ticker': 'D', 'frequency': 'daily', 'title': 'Highest temperature in D',
             'settlement_sources': [{'name': 'NWS Climatological Report Houston'}]},
            {'ticker': 'E', 'frequency': 'daily', 'title': 'Lowest temperature in E',
             'settlement_sources': None},
            {'ticker': 'C', 'frequency': 'hourly', 'title': 'Temperature in C',
             'settlement_sources': [{'name': 'National Weather Service'}]}]}
        result = inventory(client)
        self.assertEqual(result['source_counts'], {'The Weather Company': 1, 'NWS/NOAA': 2, 'Other/unknown': 1})
        self.assertEqual(result['matching_daily_temperature_series'], 4)
        client._get.assert_called_once_with('/series', {'category': 'Climate and Weather'})

    def test_missing_series_rejected(self):
        client = Mock()
        client._get.return_value = {'series': None}
        with self.assertRaises(MarketDataError): inventory(client)

    def test_nws_listed_but_closed_is_not_tradable(self):
        client = Mock()
        client._get.side_effect = [
            {'series': [{'ticker': 'NWSHIGH', 'frequency': 'daily',
                         'title': 'Highest temperature in NWS City',
                         'settlement_sources': [{'name': 'National Weather Service'}]},
                        {'ticker': 'TWCHIGH', 'frequency': 'daily',
                         'title': 'Highest temperature in TWC City',
                         'settlement_sources': [{'name': 'The Weather Company'}]}]},
            {'markets': []}, {'markets': [{'ticker': 'TWCHIGH-T80'}]}]
        result = inventory(client, check_open=True, sleep=lambda _: None)
        self.assertEqual(result['open_source_counts'], {'The Weather Company': 1})
        self.assertFalse(result['series'][0]['has_open_market'])
        self.assertTrue(result['series'][1]['has_open_market'])


if __name__ == '__main__':
    unittest.main()
