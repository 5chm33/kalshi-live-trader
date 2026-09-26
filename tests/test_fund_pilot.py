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

    def test_exact_three_step_funding_no_cross_shard_retry(self):
        client = Mock()
        client.get_api_limits.return_value = {'usage_tier': 'advanced'}
        with tempfile.TemporaryDirectory() as temp, patch('fund_pilot.private_get') as get, \
                patch('fund_pilot.balance') as balance, patch('fund_pilot.once_post') as post, \
                patch('fund_pilot.time.sleep'):
            path = Path(temp) / 'funding.json'
            get.side_effect = lambda c, endpoint: (
                {'subaccount_balances': [{'subaccount_number': 0}]} if 'balances' in endpoint else
                {'transfer': {'transfer_id': 'transfer-1234', 'status': 'complete',
                              'source': 'event_contract', 'destination': 'event_contract',
                              'source_exchange_shard': 0, 'destination_exchange_shard': 3,
                              'amount': '2.0000'}})
            seen = []

            def current_cash(_client, sub, shard):
                if (sub, shard) == (0, 0):
                    return D('10.00')
                if (sub, shard) == (0, 3):
                    count = sum(1 for x in seen if x == 'cross')
                    return D('2.00') if count == 1 and 'sub' not in seen else D(0)
                if (sub, shard) == (1, 3):
                    return D('2.00') if 'sub' in seen else D(0)
                self.fail('Unexpected account/shard read')

            def single_write(_client, endpoint, body):
                stage = json.loads(path.read_text())['stage']
                if endpoint.endswith('intra_exchange_instance_transfer'):
                    self.assertEqual(stage, 'cross_shard_submitting')
                    self.assertEqual(body['amount'], 20000)
                    self.assertEqual((body['source'], body['destination']),
                                     ('event_contract', 'event_contract'))
                    self.assertEqual((body['source_exchange_shard'], body['destination_exchange_shard']), (0, 3))
                    seen.append('cross')
                    return {'transfer_id': 'transfer-1234'}
                if endpoint.endswith('subaccounts'):
                    self.assertEqual(stage, 'create_subaccount_submitting')
                    self.assertEqual(body, {'exchange_index': 3})
                    seen.append('create')
                    return {'subaccount_number': 1}
                self.assertEqual(stage, 'subaccount_transfer_submitting')
                self.assertEqual(body['amount_cents'], 200)
                self.assertEqual(body['exchange_index'], 3)
                seen.append('sub')
                return {}

            balance.side_effect = current_cash
            post.side_effect = single_write
            self.assertEqual(fund(client, path)['stage'], 'funded')
            self.assertEqual(seen, ['cross', 'create', 'sub'])
            self.assertEqual(fund(client, path)['subaccount'], 1)
            self.assertEqual(seen, ['cross', 'create', 'sub'])

    def test_resumes_acknowledged_transfer_without_second_cross_write(self):
        client = Mock()
        with tempfile.TemporaryDirectory() as temp, patch('fund_pilot.private_get') as get, \
                patch('fund_pilot.balance') as balance, patch('fund_pilot.once_post') as post:
            path = Path(temp) / 'funding.json'
            save_stage(path, {'stage': 'cross_shard_pending', 'amount_dollars': '2.00',
                              'source_shard': 0, 'target_shard': 3, 'transfer_id': 'transfer-1234'})
            get.side_effect = lambda c, endpoint: (
                {'subaccount_balances': [{'subaccount_number': 0}]} if 'balances' in endpoint else
                {'transfer': {'transfer_id': 'transfer-1234', 'status': 'complete',
                              'source': 'event_contract', 'destination': 'event_contract',
                              'source_exchange_shard': 0, 'destination_exchange_shard': 3,
                              'amount': '2.0000'}})
            balance.side_effect = lambda _c, sub, shard: (
                D('2.00') if (sub, shard) == (0, 3) else D('1.00'))
            post.side_effect = lambda _c, endpoint, body: {'subaccount_number': 1}
            with self.assertRaisesRegex(VenueError, 'unexpectedly has cash'):
                fund(client, path)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.args[1], '/portfolio/subaccounts')
            self.assertEqual(json.loads(path.read_text())['stage'], 'created')


if __name__ == '__main__':
    unittest.main()
