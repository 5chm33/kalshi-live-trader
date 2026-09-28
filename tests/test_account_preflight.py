"""Authenticated preflight tests with mocked clients; no network or credentials."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from account_preflight import inspect, secure_config
from core.kalshi_client import KalshiClient


class ConfigTests(unittest.TestCase):
    def test_reject_world_readable_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"api_key": "fake", "private_key_string": "fake"}))
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                secure_config(path)

    def test_accept_private_config_without_printing_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"api_key": "fake", "private_key_string": "fake"}))
            path.chmod(0o600)
            self.assertEqual(secure_config(path)["api_key"], "fake")

    def test_missing_config_fails(self):
        with self.assertRaises(FileNotFoundError):
            secure_config(Path("/nonexistent/kalshi-config.json"))


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(spec=KalshiClient)
        self.client.private_key = object()
        self.client.get_account_snapshot.return_value = {
            "cash_dollars": "10.0000", "position_mark_dollars": "0.0000", "updated_ts": 0}
        self.client.get_positions.return_value = []
        self.client.get_resting_orders.return_value = []
        self.client.get_fills.return_value = []

    def test_no_positions_and_orders_is_flat_only_if_reads_succeeded(self):
        report = inspect(self.client)
        self.assertEqual(report["open_position_count"], 0)
        self.assertEqual(report["resting_order_count"], 0)
        self.assertFalse(report["trading_enabled"])
        self.client.place_ioc.assert_not_called()

    def test_does_not_swallow_account_errors(self):
        self.client.get_positions.side_effect = RuntimeError("positions request failed")
        with self.assertRaisesRegex(RuntimeError, "positions request failed"):
            inspect(self.client)

    def test_rejects_malformed_order_position_and_fill(self):
        self.client.get_positions.return_value = [{"ticker": "X", "position_fp": "NaN"}]
        with self.assertRaises(ValueError):
            inspect(self.client)
        self.client.get_positions.return_value = []
        self.client.get_resting_orders.return_value = [{"ticker": "X", "order_id": "y", "remaining_count_fp": "0"}]
        with self.assertRaises(ValueError):
            inspect(self.client)
        self.client.get_resting_orders.return_value = []
        self.client.get_fills.return_value = [{"ticker": "X", "fill_id": "z"}]
        with self.assertRaises(ValueError):
            inspect(self.client)

    def test_resting_order_pagination_failure_is_fatal(self):
        client = KalshiClient({})
        client._request = Mock(side_effect=[
            {"orders": [{"ticker": "A"}], "cursor": "more"}, None])
        with self.assertRaisesRegex(RuntimeError, "Cannot verify resting orders"):
            client.get_resting_orders()

    def test_account_snapshot_errors_not_default_zero(self):
        client = KalshiClient({})
        client._request = Mock(return_value={"balance_dollars": "10.00"})
        with self.assertRaisesRegex(RuntimeError, "fields invalid"):
            client.get_account_snapshot()


if __name__ == "__main__":
    unittest.main()
