"""Offline shadow-P&L tests using synthetic quote records, never pretend fills."""
from datetime import datetime, timedelta, timezone
import unittest

from shadow_performance import evaluate

T = datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)


def candidate():
    return {"type": "candidate", "observed_at": T.isoformat(), "ticker": "KX-EXAMPLE",
            "side": "BUY_YES_SHADOW_ONLY", "best_ask": "0.40", "ask_size": "2",
            "estimated_entry_fee_per_contract": "0.02"}


def quote(seconds=65, bid="0.46", depth="2"):
    return {"type": "quote", "observed_at": (T+timedelta(seconds=seconds)).isoformat(),
            "ticker": "KX-EXAMPLE", "yes_bid": bid, "no_ask_size": depth}


class ShadowTests(unittest.TestCase):
    def test_no_candidates_has_no_win_rate_or_fake_zero_pnl(self):
        result = evaluate([quote()])
        self.assertEqual(result['candidate_count'], 0)
        self.assertIsNone(result['hypothetical_positive_rate'])
        self.assertIsNone(result['sum_estimated_net_one_contract_dollars'])

    def test_insufficient_depth_and_missing_exit_remain_unresolved(self):
        result = evaluate([candidate(), quote(depth="0.5")])
        self.assertEqual(result['unresolved_count'], 1)
        self.assertEqual(result['priced_exit_count'], 0)
        self.assertIsNone(result['hypothetical_positive_rate'])
        result = evaluate([candidate(), quote(seconds=301)])
        self.assertEqual(result['unresolved_count'], 1)
        thin = candidate()
        thin['ask_size'] = '0.5'
        result = evaluate([thin, quote()])
        self.assertEqual(result['priced_exit_count'], 0)

    def test_evaluable_outcome_accounts_for_real_later_bid_and_estimated_fee(self):
        result = evaluate([candidate(), quote(bid="0.46")])
        self.assertEqual(result['priced_exit_count'], 1)
        self.assertEqual(result['positive_hypothetical_outcomes'], 1)
        self.assertEqual(result['hypothetical_positive_rate'], '1')
        self.assertEqual(result['rows'][0]['status'], 'observed_hypothetical')
        self.assertEqual(result['rows'][0]['net_per_contract_est'], '0.02')

    def test_data_error_aborts_instead_of_fabricating_success(self):
        with self.assertRaisesRegex(ValueError, 'data error'):
            evaluate([candidate(), {"type": "cycle_error"}, quote()])

    def test_overlapping_signals_do_not_reuse_one_contract_of_exit_depth(self):
        second = candidate()
        second['observed_at'] = (T+timedelta(seconds=1)).isoformat()
        result = evaluate([candidate(), second, quote(depth='1')])
        self.assertEqual(result['priced_exit_count'], 1)
        self.assertEqual(result['unresolved_count'], 1)
        self.assertIn('Overlapping', result['rows'][1]['reason'])

    def test_no_side_or_unknown_side_cannot_be_valued_as_yes(self):
        bad = candidate()
        bad['side'] = 'BUY_NO_SHADOW_ONLY'
        with self.assertRaisesRegex(ValueError, 'NO cannot'):
            evaluate([bad, quote()])


if __name__ == '__main__':
    unittest.main()
