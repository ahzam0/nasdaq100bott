"""
Full testing of Yahoo WebSocket integration (data/yahoo_ws_realtime.py).
- Unit: _extract_price with various message shapes; YahooWSClient getters and lifecycle.
- Mocked WS: simulate yfinance WebSocket messages and assert client updates price.
- Live (optional): real connection; skip or pass based on whether price received in time.
Run: python -m pytest tests/test_yahoo_ws.py -v
      python -m unittest tests.test_yahoo_ws -v
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------- Unit: price extraction ----------
class TestExtractPrice(unittest.TestCase):
    """Test _extract_price with every message shape we support."""

    def _extract(self, msg):
        from data.yahoo_ws_realtime import _extract_price
        return _extract_price(msg)

    def test_non_dict_returns_none(self):
        self.assertIsNone(self._extract(None))
        self.assertIsNone(self._extract("string"))
        self.assertIsNone(self._extract(123))
        self.assertIsNone(self._extract([]))

    def test_flat_price_keys(self):
        self.assertEqual(self._extract({"regularMarketPrice": 450.25}), 450.25)
        self.assertEqual(self._extract({"price": 451.0}), 451.0)
        self.assertEqual(self._extract({"lastPrice": 449.5}), 449.5)
        self.assertEqual(self._extract({"close": 452.0}), 452.0)
        self.assertEqual(self._extract({"regularMarketPreviousClose": 448.0}), 448.0)
        self.assertEqual(self._extract({"marketPrice": 447.25}), 447.25)
        self.assertEqual(self._extract({"previousClose": 446.5}), 446.5)

    def test_invalid_price_ignored(self):
        self.assertIsNone(self._extract({"price": -1}))  # negative
        self.assertIsNone(self._extract({"price": 0}))
        self.assertIsNone(self._extract({"price": 1e8}))  # too large
        self.assertIsNone(self._extract({"price": "not a number"}))
        self.assertIsNone(self._extract({"price": None}))

    def test_nested_dict(self):
        self.assertEqual(self._extract({"quote": {"price": 455.0}}), 455.0)
        self.assertEqual(self._extract({"data": {"marketPrice": 456.5}}), 456.5)
        self.assertEqual(self._extract({"payload": {"quote": {"lastPrice": 454.25}}}), 454.25)

    def test_first_valid_wins(self):
        # First key in our list that has valid number is used
        msg = {"regularMarketPrice": 100.0, "price": 200.0}
        self.assertEqual(self._extract(msg), 100.0)


# ---------- Unit: YahooWSClient (no network) ----------
class TestYahooWSClient(unittest.TestCase):
    """Test client API and lifecycle without real WebSocket."""

    def test_client_defaults(self):
        from data.yahoo_ws_realtime import YahooWSClient, YAHOO_WS_SYMBOL, DEFAULT_QQQ_TO_NQ_RATIO
        c = YahooWSClient()
        self.assertIsNone(c.get_last_price())
        self.assertIsNone(c.get_nq_equivalent_price())
        self.assertFalse(c.is_connected())
        self.assertEqual(c._symbol, YAHOO_WS_SYMBOL)
        self.assertEqual(c._ratio, DEFAULT_QQQ_TO_NQ_RATIO)

    def test_nq_equivalent(self):
        from data.yahoo_ws_realtime import YahooWSClient
        c = YahooWSClient(qqq_to_nq_ratio=50.0)
        c._last_quote_price = 400.0
        self.assertEqual(c.get_last_price(), 400.0)
        self.assertEqual(c.get_nq_equivalent_price(), 20000.0)
        c._ratio = 0
        self.assertIsNone(c.get_nq_equivalent_price())

    def test_stop_sets_connected_false(self):
        from data.yahoo_ws_realtime import YahooWSClient
        c = YahooWSClient()
        c._connected = True
        c.stop()
        self.assertFalse(c.is_connected())


# ---------- Mocked WebSocket: simulate yfinance so client gets price without network ----------
class TestYahooWSMocked(unittest.TestCase):
    """Patch yfinance.WebSocket so listen() invokes callback with a fake message."""

    def test_mock_websocket_delivers_price(self):
        from data import yahoo_ws_realtime

        fake_price = 448.5
        fake_msg = {"regularMarketPrice": fake_price}

        class FakeWS:
            def subscribe(self, symbols):
                pass

            def listen(self, callback):
                callback(fake_msg)

        class FakeContext:
            def __enter__(self):
                return FakeWS()
            def __exit__(self, *a):
                pass

        with patch("yfinance.WebSocket", return_value=FakeContext()):
            client = yahoo_ws_realtime.YahooWSClient(qqq_to_nq_ratio=50.0)
            t = threading.Thread(target=client._run_ws, daemon=True)
            t.start()
            # Let thread run: enter WebSocket, listen(cb) calls cb(fake_msg), then block in sleep(2)
            time.sleep(0.5)
            self.assertIsNotNone(client.get_last_price(), "Mocked WS should set price")
            self.assertEqual(client.get_last_price(), fake_price)
            self.assertEqual(client.get_nq_equivalent_price(), fake_price * 50.0)
            client.stop()
            t.join(timeout=3.0)


# ---------- Live integration (optional; may skip if no price in time) ----------
class TestYahooWSLive(unittest.TestCase):
    """Live test: real yfinance WebSocket. Skip if yfinance has no WebSocket or no price in 12s."""

    def test_yfinance_has_websocket(self):
        try:
            import yfinance as yf
            self.assertTrue(hasattr(yf, "WebSocket"), "yfinance must have WebSocket (pip install --upgrade yfinance)")
        except ImportError:
            self.skipTest("yfinance not installed")

    def test_create_client_and_optionally_get_price(self):
        try:
            import yfinance as yf
            if not hasattr(yf, "WebSocket"):
                self.skipTest("yfinance WebSocket not available")
        except ImportError:
            self.skipTest("yfinance not installed")

        from data.yahoo_ws_realtime import create_yahoo_ws_client, DEFAULT_QQQ_TO_NQ_RATIO

        client = create_yahoo_ws_client(qqq_to_nq_ratio=DEFAULT_QQQ_TO_NQ_RATIO)
        self.assertIsNotNone(client)
        # Wait a bit more for first message (create already waited ~10s in start())
        for _ in range(12):
            time.sleep(0.5)
            if client.get_last_price() is not None:
                nq = client.get_nq_equivalent_price()
                self.assertIsNotNone(nq)
                self.assertGreater(nq, 10000)
                self.assertLess(nq, 30000)
                client.stop()
                return
        # No price in 12s is not a failure (market closed, rate limit, etc.)
        client.stop()
        self.skipTest("No price from Yahoo WebSocket in 12s (market closed or network)")

    def test_feed_returns_some_feed(self):
        """get_feed returns a valid feed (disable Yahoo WS so we get MockDataFeed, no 10s delay)."""
        from data.feed import get_feed, MarketDataFeed, MockDataFeed
        with patch("config.USE_YAHOO_WS_REALTIME", False):
            feed = get_feed("paper", use_live_feed=False, price_api_url=None)
        self.assertIsInstance(feed, MarketDataFeed)
        self.assertIsInstance(feed, MockDataFeed)
        self.assertTrue(feed.is_connected())


if __name__ == "__main__":
    unittest.main(verbosity=2)
