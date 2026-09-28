"""Deterministic fill/book accounting tests; no live orders."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
import unittest

from core.position_valuation import exit_reason, value_position
from core.public_market import BookQuote

T = datetime(2026, 9, 25, 21, 0, tzinfo=timezone.utc)
Q = BookQuote(D("0.48"), D("0.50"), D("0.50"), D("0.52"), D("4"), D("3"))


def fill(ident, qty, yes_price, fee):
    return {"fill_id": ident, "count_fp": qty, "yes_price_dollars": yes_price,
            "fee_cost": fee}


class PositionAccountingTests(unittest.TestCase):
    def calc(self, outcome, entries, exits=(), quote=Q, delay=1, fee=D("0.01")):
        return value_position(outcome=outcome, entry_fills=entries, exit_fills=list(exits),
                              quote=quote, observed_at=T, now=T+timedelta(seconds=delay),
                              estimated_exit_fee=fee)

    def test_yes_entry_partial_exit_and_current_bid(self):
        v = self.calc("yes", [fill("entry", "2", "0.4000", "0.02")],
                      [fill("exit", "1", "0.4800", "0.01")])
        self.assertEqual(v.remaining_count, D("1"))
        self.assertEqual(v.realized_pnl, D("0.06"))
        self.assertEqual(v.estimated_unrealized_pnl, D("0.06"))
        self.assertEqual(exit_reason(v, entered_at=T, now=T+timedelta(seconds=1)), "profit_target")

    def test_no_prices_are_complements_on_both_entry_and_exit(self):
        v = self.calc("no", [fill("entry", "2", "0.6000", "0.02")],
                      [fill("exit", "1", "0.5000", "0.01")])
        self.assertEqual(v.entry_cost_total, D("0.82"))
        self.assertEqual(v.realized_pnl, D("0.08"))
        self.assertEqual(v.estimated_unrealized_pnl, D("0.08"))
        self.assertEqual(v.estimated_total_pnl, D("0.16"))

    def test_full_exit_no_unrealized_fee(self):
        v = self.calc("yes", [fill("entry", "1", "0.4000", "0.01")],
                      [fill("exit", "1", "0.4800", "0.01")])
        self.assertEqual(v.remaining_count, 0)
        self.assertEqual(v.estimated_unrealized_pnl, 0)
        self.assertIsNone(exit_reason(v, entered_at=T, now=T))

    def test_stale_quote_and_insufficient_depth_are_not_fake_pnl(self):
        for delay in [3, -1]:
            with self.assertRaises(ValueError):
                self.calc("yes", [fill("entry", "1", "0.4", "0")], delay=delay)
        with self.assertRaisesRegex(ValueError, "depth"):
            self.calc("yes", [fill("entry", "4", "0.4", "0")])

    def test_bad_fill_ids_and_negative_or_nonfinite_values_rejected(self):
        cases = [[fill("same", "1", "0.4", "0"), fill("same", "1", "0.4", "0")],
                 [fill("nan", "NaN", "0.4", "0")],
                 [fill("neg", "1", "0.4", "-0.01")]]
        for entries in cases:
            with self.assertRaises(ValueError):
                self.calc("yes", entries)

    def test_stop_and_timeout_request_are_not_guaranteed_exits(self):
        low = BookQuote(D("0.30"), D("0.32"), D("0.68"), D("0.70"), D("4"), D("4"))
        v = self.calc("yes", [fill("entry", "1", "0.40", "0.01")], quote=low)
        self.assertEqual(exit_reason(v, entered_at=T, now=T+timedelta(seconds=1)), "loss_cut_request")
        near = self.calc("yes", [fill("entry", "1", "0.47", "0.01")])
        self.assertEqual(exit_reason(near, entered_at=T-timedelta(minutes=6), now=T),
                         "time_exit_request")


if __name__ == "__main__":
    unittest.main()
