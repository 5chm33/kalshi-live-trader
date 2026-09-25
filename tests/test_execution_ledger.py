"""Offline SQLite lifecycle invariants with synthetic fills only."""
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from core.execution_ledger import LedgerError, OrderLedger
from core.order_math import plan


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "orders.sqlite"
        self.ledger = OrderLedger(self.path)
        self.item = plan("yes", "buy", 2, D("0.3000"))

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def submit(self, client_id="one", fill="1.00", remaining="0.00"):
        self.ledger.prepare(client_id, "KX-TEST", self.item)
        self.ledger.begin_submit(client_id)
        self.ledger.record_ack(client_id, {"client_order_id": client_id,
            "order_id": "exchange-" + client_id, "fill_count": fill,
            "remaining_count": remaining})

    def fill(self, client_id="one", fill_id="fill-one", count="1.00", yes_price="0.3000"):
        self.ledger.record_fill(client_id, {"order_id": "exchange-" + client_id,
            "fill_id": fill_id, "count_fp": count,
            "yes_price_dollars": yes_price, "fee_cost": "0.01", "subaccount_number": 0})

    def terminal(self, client_id, ticker, book_side, initial, filled, status='executed',
                 yes_price='0.3000'):
        self.ledger.attach_observed_order(client_id, {
            'client_order_id': client_id, 'order_id': 'exchange-' + client_id,
            'ticker': ticker, 'book_side': book_side, 'yes_price_dollars': yes_price,
            'subaccount_number': 0,
            'initial_count_fp': str(initial), 'fill_count_fp': str(filled),
            'remaining_count_fp': '0', 'status': status})

    def test_partial_fill_blocks_new_orders_and_false_flat(self):
        self.submit()
        self.fill()
        self.assertEqual(self.ledger.snapshot("one")["confirmed_fill_count"], "1.00")
        with self.assertRaises(LedgerError):
            self.ledger.prepare("two", "KX-OTHER", self.item)
        with self.assertRaises(LedgerError):
            self.ledger.record_verified_flat("one", order_terminal=True, exchange_position_size=D("1"))
        with self.assertRaises(LedgerError):
            self.ledger.record_verified_flat("one", order_terminal=False, exchange_position_size=D("0"))

    def test_duplicate_fill_is_idempotent_but_conflict_halting(self):
        self.submit()
        self.fill()
        self.fill()
        self.assertEqual(self.ledger.filled_quantity("one"), D("1"))
        with self.assertRaisesRegex(LedgerError, "Conflicting duplicate"):
            self.fill(count="2.00")
        self.assertEqual(self.ledger.snapshot("one")["phase"], "uncertain")

    def test_timeout_must_never_retry_and_survives_restart(self):
        self.ledger.prepare("one", "KX-TEST", self.item)
        self.ledger.begin_submit("one")
        self.ledger.mark_uncertain("one", "POST timeout")
        self.ledger.close()
        self.ledger = OrderLedger(self.path)
        self.assertEqual(self.ledger.snapshot("one")["phase"], "uncertain")
        with self.assertRaises(LedgerError):
            self.ledger.begin_submit("one")
        with self.assertRaises(LedgerError):
            self.ledger.prepare("two", "KX-TEST", self.item)

    def test_only_unsubmitted_intent_may_be_abandoned(self):
        self.ledger.prepare("one", "KX-TEST", self.item)
        self.ledger.abandon_prepared("one")
        self.ledger.prepare("two", "KX-TEST", self.item)
        self.ledger.begin_submit("two")
        with self.assertRaises(LedgerError):
            self.ledger.abandon_prepared("two")

    def test_daily_attempt_cap_counts_post_only_not_prepared_and_leaves_exit_possible(self):
        for i in range(3):
            cid = f'entry-{i}'
            self.ledger.prepare(cid, 'KX-TEST', self.item)
            self.ledger.begin_submit(cid)
            self.ledger.record_ack(cid, {'client_order_id': cid,
                'order_id': 'exchange-' + cid, 'fill_count': '0', 'remaining_count': '0'})
            self.terminal(cid, 'KX-TEST', 'bid', 2, 0, 'canceled')
            self.ledger.record_verified_flat(cid, order_terminal=True,
                                             exchange_position_size=D('0'))
        self.ledger.prepare('fourth', 'KX-TEST', self.item)
        with self.assertRaisesRegex(LedgerError, 'Daily new-entry attempt cap'):
            self.ledger.begin_submit('fourth')
        self.assertEqual(self.ledger.snapshot('fourth')['phase'], 'prepared')
        self.ledger.abandon_prepared('fourth')
        # The cap is defined by exchange-attempt time, not creation time.
        self.ledger.db.execute("UPDATE intents SET submitted_at=datetime('now','-1 day')")
        self.ledger.prepare('tomorrow', 'KX-TEST', self.item)
        self.ledger.begin_submit('tomorrow')
        self.ledger.record_ack('tomorrow', {'client_order_id': 'tomorrow',
            'order_id': 'exchange-tomorrow', 'fill_count': '1', 'remaining_count': '0'})
        self.fill('tomorrow', 'tomorrow-fill')
        self.terminal('tomorrow', 'KX-TEST', 'bid', 2, 1, 'canceled')
        self.ledger.prepare('safe-exit', 'KX-TEST', plan('yes', 'sell', 1, D('0.33')),
                            verified_position_size=D('1'))
        self.ledger.begin_submit('safe-exit')
        self.assertEqual(self.ledger.snapshot('safe-exit')['phase'], 'submitting')

    def test_timeout_can_attach_only_to_validated_venue_order(self):
        self.ledger.prepare('one', 'KX-TEST', self.item)
        self.ledger.begin_submit('one')
        self.ledger.mark_uncertain('one', 'POST timeout')
        with self.assertRaises(LedgerError):
            self.ledger.attach_observed_order('one', {'order_id': 'wrong'})
        self.assertEqual(self.ledger.snapshot('one')['phase'], 'uncertain')
        self.terminal('one', 'KX-TEST', 'bid', 2, 1, 'canceled')
        self.fill()
        self.assertEqual(self.ledger.snapshot('one')['phase'], 'reconcile')
        with self.assertRaises(LedgerError):
            self.ledger.prepare('two', 'KX-TEST', self.item)

    def test_verified_unfilled_ioc_may_close_and_release(self):
        self.submit(fill="0.00", remaining="0.00")
        self.terminal('one', 'KX-TEST', 'bid', 2, 0, 'canceled')
        self.ledger.record_verified_flat("one", order_terminal=True, exchange_position_size=D("0"))
        self.ledger.prepare("two", "KX-OTHER", self.item)

    def test_filled_entrance_stays_open_until_venue_flat(self):
        self.submit()
        self.fill()
        with self.assertRaises(LedgerError):
            self.ledger.record_verified_flat("one", order_terminal=True, exchange_position_size=D("1"))
        with self.assertRaises(LedgerError):
            self.ledger.record_verified_flat("one", order_terminal=True, exchange_position_size=D("0"))
        self.assertEqual(self.ledger.snapshot("one")["phase"], "reconcile")

    def test_exit_requires_bot_fill_and_actual_held_position(self):
        exit_plan = plan("yes", "sell", 1, D("0.33"))
        with self.assertRaises(LedgerError):
            self.ledger.prepare("out", "KX-TEST", exit_plan, verified_position_size=D("1"))
        self.submit()
        self.fill()
        self.terminal('one', 'KX-TEST', 'bid', 2, 1, 'canceled')
        with self.assertRaises(LedgerError):
            self.ledger.prepare("out", "KX-TEST", exit_plan, verified_position_size=D("0"))
        self.ledger.prepare("out", "KX-TEST", exit_plan, verified_position_size=D("1"))
        with self.assertRaises(LedgerError):
            self.ledger.prepare("other", "KX-TEST", exit_plan, verified_position_size=D("1"))

    def test_confirmed_full_exit_releases_both_entry_and_exit(self):
        self.submit()
        self.fill()
        self.terminal('one', 'KX-TEST', 'bid', 2, 1, 'canceled')
        exit_plan = plan("yes", "sell", 1, D("0.33"))
        self.ledger.prepare("out", "KX-TEST", exit_plan, verified_position_size=D("1"))
        self.ledger.begin_submit("out")
        self.ledger.record_ack("out", {"client_order_id": "out", "order_id": "exchange-out",
                                      "fill_count": "1", "remaining_count": "0"})
        self.fill("out", "exit-fill", yes_price="0.3300")
        self.terminal('out', 'KX-TEST', 'ask', 1, 1, yes_price='0.3300')
        self.ledger.record_verified_flat("out", order_terminal=True, exchange_position_size=D("0"))
        self.assertEqual(self.ledger.snapshot("one")["phase"], "verified_flat")
        self.ledger.prepare("next", "KX-OTHER", self.item)

    def test_partial_exit_requires_reconciled_second_exit(self):
        self.submit(fill="2", remaining="0")
        self.fill(count="2")
        self.terminal('one', 'KX-TEST', 'bid', 2, 2)
        first = plan("yes", "sell", 2, D("0.33"))
        self.ledger.prepare("first", "KX-TEST", first, verified_position_size=D("2"))
        self.ledger.begin_submit("first")
        self.ledger.record_ack("first", {"client_order_id": "first", "order_id": "exchange-first",
                                        "fill_count": "1", "remaining_count": "0"})
        self.fill("first", "first-fill", "1", yes_price="0.3300")
        self.terminal('first', 'KX-TEST', 'ask', 2, 1, 'canceled', yes_price='0.3300')
        with self.assertRaises(LedgerError):
            self.ledger.record_verified_flat("first", order_terminal=True, exchange_position_size=D("0"))
        self.ledger.record_partial_exit_terminal("first", order_terminal=True,
                                                 verified_position_size=D("1"))
        second = plan("yes", "sell", 1, D("0.34"))
        self.ledger.prepare("second", "KX-TEST", second, verified_position_size=D("1"))
        self.ledger.begin_submit("second")
        self.ledger.record_ack("second", {"client_order_id": "second", "order_id": "exchange-second",
                                         "fill_count": "1", "remaining_count": "0"})
        self.fill("second", "second-fill", "1", yes_price="0.3400")
        self.terminal('second', 'KX-TEST', 'ask', 1, 1, yes_price='0.3400')
        self.ledger.record_verified_flat("second", order_terminal=True, exchange_position_size=D("0"))
        self.assertEqual(self.ledger.snapshot("first")["phase"], "verified_flat")
        self.assertEqual(self.ledger.snapshot("one")["phase"], "verified_flat")

    def test_no_contract_entry_and_exit_use_negative_venue_position(self):
        no_entry = plan("no", "buy", 1, D("0.30"))
        no_exit = plan("no", "sell", 1, D("0.33"))
        self.ledger.prepare("no-in", "KX-NO", no_entry)
        self.ledger.begin_submit("no-in")
        self.ledger.record_ack("no-in", {"client_order_id": "no-in", "order_id": "exchange-no-in",
                                         "fill_count": "1", "remaining_count": "0"})
        self.ledger.record_fill("no-in", {"order_id": "exchange-no-in", "fill_id": "no-fill",
            "count_fp": "1", "yes_price_dollars": "0.7000", "fee_cost": "0.01",
            "subaccount_number": 0})
        self.terminal('no-in', 'KX-NO', 'ask', 1, 1, yes_price='0.7000')
        with self.assertRaises(LedgerError):
            self.ledger.prepare("no-out", "KX-NO", no_exit, verified_position_size=D("1"))
        self.ledger.prepare("no-out", "KX-NO", no_exit, verified_position_size=D("-1"))
        self.ledger.begin_submit("no-out")
        self.ledger.record_ack("no-out", {"client_order_id": "no-out", "order_id": "exchange-no-out",
                                          "fill_count": "1", "remaining_count": "0"})
        self.ledger.record_fill("no-out", {"order_id": "exchange-no-out", "fill_id": "no-exit-fill",
            "count_fp": "1", "yes_price_dollars": "0.6700", "fee_cost": "0.01",
            "subaccount_number": 0})
        self.terminal('no-out', 'KX-NO', 'bid', 1, 1, yes_price='0.6700')
        self.ledger.record_verified_flat("no-out", order_terminal=True, exchange_position_size=D("0"))
        self.assertEqual(self.ledger.snapshot("no-in")["phase"], "verified_flat")

    def test_exclusive_lock_and_private_mode(self):
        with self.assertRaises(LedgerError):
            OrderLedger(self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_malformed_ack_fails_closed(self):
        self.ledger.prepare("one", "KX-TEST", self.item)
        self.ledger.begin_submit("one")
        with self.assertRaises(LedgerError):
            self.ledger.record_ack("one", {"client_order_id": "wrong", "order_id": "e",
                                           "fill_count": "0", "remaining_count": "2"})
        self.assertEqual(self.ledger.snapshot("one")["phase"], "uncertain")

    def test_observed_limit_mismatch_does_not_attach(self):
        self.ledger.prepare('one', 'KX-TEST', self.item)
        self.ledger.begin_submit('one')
        with self.assertRaises(LedgerError):
            self.terminal('one', 'KX-TEST', 'bid', 2, 0, yes_price='0.3100')
        self.assertEqual(self.ledger.snapshot('one')['phase'], 'uncertain')

    def test_out_of_limit_fill_halts_reconciliation(self):
        self.submit(fill='1', remaining='0')
        with self.assertRaisesRegex(LedgerError, 'Malformed fill'):
            self.fill(yes_price='0.31')
        self.assertEqual(self.ledger.snapshot('one')['phase'], 'uncertain')


if __name__ == "__main__":
    unittest.main()
