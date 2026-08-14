from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from research.capture_mlb_ws import _book_payload
from research.models import BookLevel, CanonicalBook, SourceStamp


class CaptureTimingTests(unittest.TestCase):
    def test_poll_to_book_timing_is_labeled_without_claiming_event_time(self) -> None:
        game_received = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)
        received = game_received + timedelta(milliseconds=200)
        book = CanonicalBook(
            "T", (BookLevel(Decimal("0.40"), Decimal("1")),), (BookLevel(Decimal("0.60"), Decimal("1")),),
            SourceStamp("ws", received, None, "h"),
        )
        payload = _book_payload(book, {"sid": 1, "seq": 2, "type": "orderbook_snapshot"}, game_received, None)
        self.assertEqual(200.0, payload["game_poll_to_book_ms"])
        self.assertFalse(payload["game_source_event_time_available"])
        self.assertIsNone(payload["game_source_at"])


if __name__ == "__main__":
    unittest.main()
