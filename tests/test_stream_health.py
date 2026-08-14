from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from research.stream_health import StreamHealth


class StreamHealthTests(unittest.TestCase):
    def test_counters_and_source_delay_are_recorded(self) -> None:
        health = StreamHealth()
        source_at = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)
        health.connected()
        health.connected()
        health.message(source_at, source_at + timedelta(milliseconds=125))
        health.gap()
        health.resynced()
        health.errored()
        payload = health.payload()
        self.assertEqual(2, payload["connects"])
        self.assertEqual(1, payload["reconnects"])
        self.assertEqual(1, payload["sequence_gaps"])
        self.assertEqual(1, payload["resyncs"])
        self.assertEqual("125.0", payload["max_source_to_receipt_ms"])


if __name__ == "__main__":
    unittest.main()
