"""Mocked account-funding tests; do not move or spend any real cash."""
import json
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import Mock, patch

from core.pilot_venue import VenueError
from fund_pilot import CAP, TRANSFER_CENTICENTS, TRANSFER_CENTS, fund, once_post, save_stage


class FundingTests(unittest.TestCase):
    def test_units_and_cap_are_exact(self):
        self.assertEqual(CAP, D('2.00'))
        self.assertEqual(TRANSFER_CENTICENTS, 20000)
        self.assertEqual(TRANSFER_CENTS, 200)

    def test_owner_only_funding_stage_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'funding.json'
            save_stage(path, {'stage': 'cross_shard_submitting'})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['stage'], 'cross_shard_submitting')
            with self.assertRaises(VenueError):
                fund(Mock(), path)

    def test_signed_post_once_never_retries_timeout(self):
        client = Mock()
        client.base_url = 'https://external-api.kalshi.com'
        client._auth_headers.return_value = {'KALSHI-ACCESS-KEY': 'mock'}
        client.session.post.side_effect = TimeoutError('ambiguous')
        with self.assertRaisesRegex(VenueError, 'do not repeat'):
            once_post(client, '/portfolio/intra_exchange_instance_transfer', {'amount': 20000})
        client.session.post.assert_called_once()
        self.assertEqual(client.session.post.call_args.kwargs['json']['amount'], 20000)
        self.assertEqual(client.session.post.call_args.kwargs['verify'], True)
        self.assertEqual(client.session.post.call_args.kwargs['allow_redirects'], False)

    def test_preflight_halts_on_unknown_subaccount_without_write(self):
        client = Mock()
        client.get_api_limits.return_value = {'usage_tier': 'advanced'}
        with tempfile.TemporaryDirectory() as temp, patch('fund_pilot.private_get') as get, patch('fund_pilot.once_post') as post:
            get.return_value = {'subaccount_balances': [{'subaccount_number': 0},
                                                        {'subaccount_number': 1}]}
            with self.assertRaises(VenueError):
                fund(client, Path(temp) / 'funding.json')
            post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
