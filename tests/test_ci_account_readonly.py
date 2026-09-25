"""GET-only CI account diagnostic tests with no real credentials."""
import unittest
from unittest.mock import Mock

from scripts.ci_account_readonly import check


class AccountCiTests(unittest.TestCase):
    def test_sanitized_summary_has_no_key_or_positions(self):
        c = Mock(private_key=object())
        c.get_api_limits.return_value = {'usage_tier': 'advanced',
                                         'read': {'refill_rate': 300},
                                         'write': {'refill_rate': 300}}
        c.get_account_snapshot.return_value = {'cash_dollars': '10.00'}
        c.get_positions.return_value = [{'ticker': 'EXAMPLE'}]
        c.get_resting_orders.return_value = []
        result = check(c)
        self.assertEqual(result['effective_tier'], 'advanced')
        self.assertEqual(result['primary_open_position_count'], 1)
        self.assertNotIn('cash_dollars', result)
        self.assertNotIn('ticker', result)
        c.place_ioc.assert_not_called()
        c.cancel_order.assert_not_called()

    def test_failed_account_get_never_implies_empty(self):
        c = Mock(private_key=object())
        c.get_api_limits.side_effect = RuntimeError('tier GET failed')
        with self.assertRaisesRegex(RuntimeError, 'tier GET failed'):
            check(c)
        c.place_ioc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
