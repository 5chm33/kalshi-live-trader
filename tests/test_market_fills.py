"""Private GET pagination tests with mocked Kalshi responses."""
import unittest
from unittest.mock import Mock

from core.kalshi_client import KalshiClient


class MarketFillsTests(unittest.TestCase):
    def setUp(self):
        self.client = KalshiClient({})
        self.client._request = Mock()

    def test_live_and_historical_tiers_are_independent(self):
        self.client._request.side_effect = [
            {"fills": [{"fill_id": "live"}], "cursor": "NEXT"},
            {"fills": [{"fill_id": "live2"}], "cursor": ""},
            {"fills": [{"fill_id": "old"}], "cursor": ""},
        ]
        live = self.client.get_market_fills('KX-TEST')
        older = self.client.get_market_fills('KX-TEST', historical=True)
        self.assertEqual([x['fill_id'] for x in live], ['live', 'live2'])
        self.assertEqual([x['fill_id'] for x in older], ['old'])
        self.assertIn('cursor=NEXT', self.client._request.call_args_list[1].args[1])
        self.assertIn('subaccount=0', self.client._request.call_args_list[0].args[1])
        self.assertIn('/historical/fills?', self.client._request.call_args.args[1])

    def test_truncated_or_looped_page_aborts(self):
        self.client._request.side_effect = [{"fills": [], "cursor": "again"}, None]
        with self.assertRaises(RuntimeError):
            self.client.get_market_fills('KX-TEST')
        self.client._request.side_effect = [{"fills": [], "cursor": "again"},
                                            {"fills": [], "cursor": "again"}]
        with self.assertRaises(RuntimeError):
            self.client.get_market_fills('KX-TEST', historical=True)

    def test_ticker_input_rejected_before_network(self):
        with self.assertRaises(ValueError):
            self.client.get_market_fills('a?limit=1000')
        self.client._request.assert_not_called()

    def test_order_status_reads_are_complete_or_halt(self):
        self.client._request.side_effect = [
            {'orders': [{'order_id': 'one'}], 'cursor': 'next'},
            {'orders': [{'order_id': 'two'}], 'cursor': ''}]
        self.assertEqual(len(self.client.get_orders_by_status('KX-TEST', 'executed')), 2)
        self.assertIn('cursor=next', self.client._request.call_args.args[1])
        with self.assertRaises(ValueError):
            self.client.get_orders_by_status('KX-TEST', 'unknown')
        self.client._request.reset_mock(side_effect=True)
        self.client._request.return_value = None
        with self.assertRaises(RuntimeError):
            self.client.get_orders_by_status('KX-TEST', 'resting')

    def test_historical_order_pages_and_errors(self):
        self.client._request.side_effect = [
            {'orders': [{'order_id': 'old'}], 'cursor': 'next'},
            {'orders': [], 'cursor': ''}]
        self.assertEqual(len(self.client.get_historical_market_orders('KX-TEST')), 1)
        self.assertIn('/historical/orders?', self.client._request.call_args.args[1])
        self.assertIn('subaccount=0', self.client._request.call_args.args[1])
        self.client._request.reset_mock(side_effect=True)
        self.client._request.return_value = {'error': 'not an order list'}
        with self.assertRaises(RuntimeError):
            self.client.get_historical_market_orders('KX-TEST')


if __name__ == '__main__':
    unittest.main()
