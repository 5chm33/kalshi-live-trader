"""No-network tier checks; the real endpoint is GET-only."""
import unittest
from unittest.mock import Mock

from core.kalshi_client import KalshiClient


class LimitsTests(unittest.TestCase):
    def setUp(self):
        self.client = KalshiClient({})
        self.client._request = Mock(return_value={
            'usage_tier': 'advanced',
            'read': {'refill_rate': 300, 'bucket_capacity': 900},
            'write': {'refill_rate': 300, 'bucket_capacity': 900},
            'grants': [{'source': 'not included in public output'}]})

    def test_effective_tier_is_read_from_authenticated_get(self):
        result = self.client.get_api_limits()
        self.assertEqual(result['usage_tier'], 'advanced')
        self.assertEqual(result['write']['refill_rate'], 300)
        self.assertNotIn('grants', result)
        self.client._request.assert_called_once_with('GET', '/account/limits')

    def test_unavailable_or_malformed_tier_aborts(self):
        for bad in [None, {}, {'usage_tier': 'unlimited'},
                    {'usage_tier': 'advanced', 'read': {'refill_rate': -1}},
                    {'usage_tier': 'advanced', 'read': {'refill_rate': 300,
                     'bucket_capacity': 900}, 'write': {'refill_rate': False,
                     'bucket_capacity': 900}}]:
            with self.subTest(bad=bad):
                self.client._request.return_value = bad
                with self.assertRaises(RuntimeError):
                    self.client.get_api_limits()


if __name__ == '__main__':
    unittest.main()
