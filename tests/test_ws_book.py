from __future__ import annotations

import unittest
from decimal import Decimal

from research.ws_book import SequenceGap, WebSocketBookSynchronizer


class WebSocketBookTests(unittest.TestCase):
    def test_snapshot_then_delta_reconstructs_book(self) -> None:
        sync = WebSocketBookSynchronizer()
        snapshot = {
            "type": "orderbook_snapshot", "sid": 7, "seq": 10,
            "msg": {
                "market_ticker": "TEST", "market_id": "id",
                "yes_dollars_fp": [["0.20", "2.00"], ["0.40", "1.00"]],
                "no_dollars_fp": [["0.30", "4.00"]],
            },
        }
        book = sync.apply(snapshot)
        assert book is not None
        self.assertEqual(book.best_yes_bid, Decimal("0.40"))
        self.assertEqual(book.best_yes_ask, Decimal("0.70"))

        delta = {
            "type": "orderbook_delta", "sid": 7, "seq": 11,
            "msg": {
                "market_ticker": "TEST", "market_id": "id", "side": "no",
                "price_dollars": "0.35", "delta_fp": "3.00", "ts_ms": 1786670000000,
            },
        }
        book = sync.apply(delta)
        assert book is not None
        self.assertEqual(book.best_no_bid, Decimal("0.35"))
        self.assertEqual(book.best_yes_ask, Decimal("0.65"))
        self.assertEqual(book.stamp.source_at.year, 2026)

    def test_delta_gap_raises_and_requires_resync(self) -> None:
        sync = WebSocketBookSynchronizer()
        sync.apply({
            "type": "orderbook_snapshot", "sid": 1, "seq": 5,
            "msg": {"market_ticker": "TEST", "market_id": "id", "yes_dollars_fp": [], "no_dollars_fp": []},
        })
        with self.assertRaises(SequenceGap):
            sync.apply({
                "type": "orderbook_delta", "sid": 1, "seq": 7,
                "msg": {"market_ticker": "TEST", "market_id": "id", "side": "yes", "price_dollars": "0.5", "delta_fp": "1"},
            })

    def test_delta_removal_deletes_empty_price_level(self) -> None:
        sync = WebSocketBookSynchronizer()
        sync.apply({
            "type": "orderbook_snapshot", "sid": 1, "seq": 1,
            "msg": {"market_ticker": "TEST", "market_id": "id", "yes_dollars_fp": [["0.50", "2"]], "no_dollars_fp": []},
        })
        book = sync.apply({
            "type": "orderbook_delta", "sid": 1, "seq": 2,
            "msg": {"market_ticker": "TEST", "market_id": "id", "side": "yes", "price_dollars": "0.50", "delta_fp": "-2"},
        })
        assert book is not None
        self.assertIsNone(book.best_yes_bid)


if __name__ == "__main__":
    unittest.main()
