"""Contract-price and pilot-sizing tests; no HTTP calls."""
from decimal import Decimal as D
import unittest

from core.order_math import executable_price, pilot_size, plan
from core.public_market import BookQuote


class V2SemanticsTests(unittest.TestCase):
    def test_fractional_sell_only_for_reduce_only_inventory(self):
        with self.assertRaises(ValueError):
            plan('yes', 'buy', D('.50'), D('.45'))
        item = plan('yes', 'sell', D('.25'), D('.46'))
        payload = item.payload('KX-TEST', 'pilot-fraction-123', reduce_only=True,
                               subaccount=1, exchange_index=3)
        self.assertEqual(payload['count'], '0.25')
        self.assertEqual(payload['side'], 'ask')
        with self.assertRaises(ValueError):
            plan('yes', 'sell', D('.001'), D('.46'))

    def test_all_four_actions_use_yes_book_price(self):
        cases = [
            ("yes", "buy", "bid", "0.3000"),
            ("yes", "sell", "ask", "0.3000"),
            ("no", "buy", "ask", "0.7000"),
            ("no", "sell", "bid", "0.7000"),
        ]
        for outcome, action, expected_side, yes_price in cases:
            with self.subTest(outcome=outcome, action=action):
                item = plan(outcome, action, 1, D("0.3000"))
                self.assertEqual(item.side, expected_side)
                self.assertEqual(str(item.yes_limit), yes_price)
                body = item.payload("KX-TEST", "abc", reduce_only=action == "sell")
                self.assertEqual(body["side"], expected_side)
                self.assertEqual(body["price"], f"{D(yes_price):.4f}")
                self.assertEqual(body["count"], "1.00")
                self.assertEqual(body["time_in_force"], "immediate_or_cancel")

    def test_sell_cannot_increase_exposure_and_entries_are_not_reduce_only(self):
        with self.assertRaises(ValueError):
            plan("no", "sell", 1, D("0.30")).payload("X", "y", reduce_only=False)
        with self.assertRaises(ValueError):
            plan("yes", "buy", 1, D("0.30")).payload("X", "y", reduce_only=True)

    def test_reject_invalid_or_off_grid_prices_and_count(self):
        for p in [D("0"), D("1"), D("NaN"), D("0.12345")]:
            with self.assertRaises(Exception):
                plan("yes", "buy", 1, p)
        for n in [0, -1, 11, True, 1.5]:
            with self.assertRaises(ValueError):
                plan("yes", "buy", n, D("0.30"))

    def test_depth_is_from_opposite_side_of_book(self):
        q = BookQuote(D("0.30"), D("0.33"), D("0.67"), D("0.70"), D("4"), D("8"))
        expected = {("yes", "buy"): (D("0.33"), D("4")),
                    ("yes", "sell"): (D("0.30"), D("8")),
                    ("no", "buy"): (D("0.70"), D("8")),
                    ("no", "sell"): (D("0.67"), D("4"))}
        for (outcome, action), value in expected.items():
            self.assertEqual(executable_price(q, outcome, action), value)
        with self.assertRaises(ValueError):
            executable_price(q, "yes", "hold")


class PilotRiskTests(unittest.TestCase):
    def make(self, **kwargs):
        data = {"available_cash": D("9.90"), "existing_exposure": D("0.10"),
                "pending_commitments": D("0"), "price": D("0.30"),
                "fee_reserve": D("0.02"), "ask_size": D("2"),
                "calibrated_net_edge": D("0.05")}
        data.update(kwargs)
        return pilot_size(**data)

    def test_positive_edge_is_required_and_no_forced_minimum(self):
        self.assertEqual(self.make(calibrated_net_edge=None), 0)
        self.assertEqual(self.make(calibrated_net_edge=D("0")), 0)
        self.assertEqual(self.make(calibrated_net_edge=D("-0.01")), 0)

    def test_absolute_cap_per_order_cap_cash_and_depth(self):
        self.assertEqual(self.make(), 1)
        self.assertEqual(self.make(available_cash=D("0.31")), 0)
        self.assertEqual(self.make(existing_exposure=D("9.75")), 0)
        self.assertEqual(self.make(pending_commitments=D("9.70")), 0)
        self.assertEqual(self.make(per_order_cap=D("0.20")), 0)
        self.assertEqual(self.make(ask_size=D("0")), 0)

    def test_invalid_or_missing_inputs_fail_closed(self):
        for options in [{"available_cash": D("NaN")}, {"existing_exposure": D("-1")},
                        {"price": D("0")}, {"ask_size": D("-1")},
                        {"calibrated_net_edge": D("Infinity")}]:
            with self.assertRaises(ValueError):
                self.make(**options)


if __name__ == "__main__":
    unittest.main()
