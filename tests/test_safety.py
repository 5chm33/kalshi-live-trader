"""Offline safety regressions; these fakes never contact a venue."""

import unittest

import main
from core.position_manager import PositionManager


class FakeExitClient:
    def __init__(self, order_result):
        self.order_result = order_result
        self.ioc_calls = []

    def get_market(self, ticker):
        return {"yes_bid_dollars": "0.75", "no_bid_dollars": "0.25"}

    def place_ioc(self, ticker, side, count, price):
        self.ioc_calls.append((ticker, side, count, price))
        return self.order_result


class LiveEntrypointSafetyTests(unittest.TestCase):
    def test_main_fails_closed_without_loading_config_or_client(self):
        original_load_config = main.load_config
        original_live_trader = main.LiveTrader
        calls = []

        def unexpected(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("disabled entrypoint must not initialize live components")

        try:
            main.load_config = unexpected
            main.LiveTrader = unexpected
            self.assertFalse(main.LIVE_EXECUTION_ENABLED)
            self.assertEqual(main.main(), 1)
            self.assertEqual(calls, [])
        finally:
            main.load_config = original_load_config
            main.LiveTrader = original_live_trader

    def test_live_trader_construction_is_disabled(self):
        with self.assertRaises(main.LiveExecutionDisabled):
            main.LiveTrader({})


class ExitFillSafetyTests(unittest.TestCase):
    def _manager_with_position(self, order_result):
        client = FakeExitClient(order_result)
        manager = PositionManager(client)
        manager.open_position(
            ticker="TEST-TICKER",
            side="yes",
            entry_price=0.50,
            contracts=5.0,
            strategy="test",
            sport="test",
            order_id="entry-order",
        )
        return manager, client

    def test_zero_ioc_fill_retains_position_without_legacy_fallback(self):
        manager, client = self._manager_with_position(
            {"order_id": "exit-order", "fill_count": "0"}
        )

        manager._exit("TEST-TICKER", "test")

        self.assertIn("TEST-TICKER", manager.positions)
        self.assertEqual(manager.positions["TEST-TICKER"].contracts, 5.0)
        self.assertEqual(manager.realized_pnl, 0.0)
        self.assertEqual(len(client.ioc_calls), 1)

    def test_partial_ioc_fill_retains_only_unfilled_contracts(self):
        manager, client = self._manager_with_position(
            {
                "order_id": "exit-order",
                "fill_count": "2",
                "average_fill_price": "0.75",
            }
        )

        manager._exit("TEST-TICKER", "test")

        self.assertIn("TEST-TICKER", manager.positions)
        self.assertEqual(manager.positions["TEST-TICKER"].contracts, 3.0)
        self.assertAlmostEqual(manager.realized_pnl, 0.50)
        self.assertEqual(manager.wins, 1)
        self.assertEqual(len(client.ioc_calls), 1)

    def test_full_ioc_fill_removes_position(self):
        manager, _ = self._manager_with_position(
            {
                "order_id": "exit-order",
                "fill_count": "5",
                "average_fill_price": "0.75",
            }
        )

        manager._exit("TEST-TICKER", "test")

        self.assertNotIn("TEST-TICKER", manager.positions)
        self.assertAlmostEqual(manager.realized_pnl, 1.25)

    def test_invalid_fill_count_is_treated_as_unconfirmed(self):
        manager, _ = self._manager_with_position(
            {"order_id": "exit-order", "fill_count": "not-a-number"}
        )

        manager._exit("TEST-TICKER", "test")

        self.assertIn("TEST-TICKER", manager.positions)
        self.assertEqual(manager.positions["TEST-TICKER"].contracts, 5.0)


if __name__ == "__main__":
    unittest.main()
