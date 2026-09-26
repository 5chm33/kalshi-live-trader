"""Synthetic orderbook fixtures only; no live WS or trading requests."""
import time
import unittest
from decimal import Decimal as D
from unittest.mock import AsyncMock, Mock, patch
from core.fresh_book import ConfirmedBook, fresh_confirmed_quote, parse_snapshot
from core.public_market import MarketDataError, quote_from_orderbook


class FreshBookTests(unittest.TestCase):
    def setUp(self):
        self.ticker = 'KXMLBGAME-TEST-A'
        self.book = {'yes_dollars': [['0.4300', '4.00']],
                     'no_dollars': [['0.5500', '3.00']]}
        self.message = {'type': 'orderbook_snapshot', 'seq': 7,
                        'msg': {'market_ticker': self.ticker,
                                'yes_dollars_fp': self.book['yes_dollars'],
                                'no_dollars_fp': self.book['no_dollars']}}

    def test_new_venue_snapshot_is_parsed_with_depth_and_sequence(self):
        snapshot = parse_snapshot(self.message, self.ticker)
        self.assertEqual(snapshot.sequence, 7)
        self.assertEqual(snapshot.quote.yes_ask, D('.4500'))
        self.assertEqual(snapshot.quote.yes_ask_size, D('3.00'))
        with self.assertRaises(MarketDataError):
            parse_snapshot(dict(self.message, seq='7'), self.ticker)
        with self.assertRaises(MarketDataError):
            parse_snapshot(self.message, 'WRONG-TICKER')

    def test_cross_channel_disagreement_or_aged_snapshot_prevents_trade(self):
        public = Mock()
        public.get_orderbook.return_value = self.book
        quote = quote_from_orderbook(self.book)
        with patch('core.fresh_book._subscribe_once', new_callable=AsyncMock,
                   return_value=ConfirmedBook(quote, 7, time.monotonic() - 2)):
            with self.assertRaisesRegex(MarketDataError, 'aged out'):
                fresh_confirmed_quote(Mock(), public, self.ticker)
        public.get_orderbook.return_value = dict(self.book, no_dollars=[['0.5400', '3.00']])
        with patch('core.fresh_book._subscribe_once', new_callable=AsyncMock,
                   return_value=ConfirmedBook(quote, 7, time.monotonic())):
            with self.assertRaisesRegex(MarketDataError, 'disagree'):
                fresh_confirmed_quote(Mock(), public, self.ticker)
        public.get_orderbook.return_value = self.book
        with patch('core.fresh_book._subscribe_once', new_callable=AsyncMock,
                   return_value=ConfirmedBook(quote, 7, time.monotonic())):
            self.assertEqual(fresh_confirmed_quote(Mock(), public, self.ticker), quote)


if __name__ == '__main__':
    unittest.main()
