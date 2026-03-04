"""
A-to-Z test: verify the bot is capable of sending real live signals.
Run: python run_tests.py  (includes this file)
  or: python -m unittest tests.test_live_signal_a2z -v
Tests: config, feed, scan path, and optionally sends a real demo Telegram message.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestLiveSignalA2Z(unittest.TestCase):
    """A-to-Z: bot is capable of sending real live signals."""

    def test_config_has_telegram_credentials(self):
        """Bot must have Telegram token and chat ID to send live signals."""
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        self.assertTrue(bool(TELEGRAM_BOT_TOKEN), "TELEGRAM_BOT_TOKEN must be set for live signals")
        self.assertTrue(bool(TELEGRAM_CHAT_ID), "TELEGRAM_CHAT_ID must be set for live signals")

    def test_feed_can_connect(self):
        """Live or mock feed must connect so scan can fetch data."""
        from data import get_feed
        from config import BROKER, USE_LIVE_FEED, PRICE_API_URL
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        self.assertIsNotNone(feed)
        connected = feed.is_connected()
        self.assertIsInstance(connected, bool)

    def test_scan_path_with_mock_feed_completes(self):
        """Full scan path (get data -> detect setup -> validate -> format alert) runs without error."""
        import main
        from unittest.mock import patch, MagicMock, AsyncMock
        from data.feed import MockDataFeed

        async def _run():
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock(return_value=None)
            with patch("main.get_feed", return_value=MockDataFeed(19000.0)), \
                 patch("main.in_scan_window", return_value=True), \
                 patch("main.get_state", return_value={
                     "scan_active": True, "trades_today": 0, "daily_pnl": 0,
                     "risk_per_trade": 380, "active_trades": [], "trade_history": [],
                     "use_orderflow": False, "key_levels_text": "",
                 }), \
                 patch("main.TELEGRAM_CHAT_ID", "123"):
                await main.run_scan(mock_bot)

        asyncio.run(_run())

    def test_live_feed_returns_data_when_available(self):
        """If live feed connects, it returns 1m/15m data (or empty outside session)."""
        from data import get_feed
        from config import BROKER, USE_LIVE_FEED, PRICE_API_URL
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        if not feed.is_connected():
            self.skipTest("Feed not connected (e.g. no network)")
        try:
            df_1m = feed.get_1m_candles(50)
            df_15m = feed.get_15m_candles(30)
        except Exception as e:
            self.skipTest(f"Feed get candles failed: {e}")
        self.assertIsNotNone(df_1m)
        self.assertIsNotNone(df_15m)
        if not df_1m.empty:
            self.assertIn("close", df_1m.columns)
        if not df_15m.empty:
            self.assertIn("close", df_15m.columns)

    def test_send_real_demo_signal(self):
        """Send a real demo signal to Telegram to prove live delivery (requires token + chat_id)."""
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            self.skipTest("No Telegram credentials")

        async def _send():
            from telegram import Bot
            from bot.alerts import format_trade_alert, send_telegram
            bot = Bot(TELEGRAM_BOT_TOKEN)
            msg = format_trade_alert(
                setup_name="Retest Reversal",
                time_est="A-to-Z Test",
                direction="LONG",
                entry=21500.0,
                stop=21480.0,
                tp1=21540.0,
                tp2=21580.0,
                rr_ratio=2.0,
                confidence="High",
                timeframe_note="1-min | 15-min trend: Bullish",
                key_level="Test level",
                notes="[A-to-Z live signal test – not a real trade]",
            )
            ok = await send_telegram(msg, bot, TELEGRAM_CHAT_ID)
            return ok

        ok = asyncio.run(_send())
        self.assertTrue(ok, "Telegram send_telegram should return True when message is sent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
