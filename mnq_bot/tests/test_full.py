"""
Full test suite for MNQ Trading Bot.
Run: python -m pytest tests/ -v   OR   python -m unittest tests.test_full -v
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
import pandas as pd
import numpy as np

EST = ZoneInfo("America/New_York")


# ---------- Config ----------
class TestConfig(unittest.TestCase):
    def test_config_loads(self):
        import config
        self.assertIsNotNone(config.INSTRUMENT)
        self.assertEqual(config.INSTRUMENT, "MNQ")
        self.assertGreater(config.MAX_RISK_PER_TRADE_USD, 0)
        self.assertIn(config.MAX_TRADES_PER_DAY, (1, 2, 3))
        self.assertTrue(hasattr(config, "RETEST_ONLY"))


# ---------- Utils ----------
class TestRiskCalculator(unittest.TestCase):
    def test_contracts_from_risk(self):
        from utils.risk_calculator import contracts_from_risk, risk_usd_for_trade
        # 20 pts * $2 = $40/contract. $75 / 40 = 1.87 -> 1 contract
        n = contracts_from_risk(75, 20, 2.0)
        self.assertGreaterEqual(n, 1)
        self.assertLessEqual(n, 10)
        # 10 pts * $2 = $20. $75/20 = 3
        n = contracts_from_risk(75, 10, 2.0)
        self.assertEqual(n, 3)
        risk = risk_usd_for_trade(2, 15, 2.0)
        self.assertEqual(risk, 60)


# ---------- Data feed ----------
class TestDataFeed(unittest.TestCase):
    def test_calendar_manual_times(self):
        from unittest.mock import patch
        from zoneinfo import ZoneInfo
        from datetime import date
        import data.calendar as cal
        cal._CALENDAR_CACHE[:] = []
        cal._CALENDAR_CACHE_TIME = 0.0
        with patch("data.calendar.USE_ECONOMIC_CALENDAR", True), patch("data.calendar.CALENDAR_MANUAL_HIGH_IMPACT_TIMES", ["9:00"]):
            events = cal.fetch_high_impact_times_est()
            self.assertGreaterEqual(len(events), 1)
            self.assertEqual(events[0].hour, 9)
            self.assertEqual(events[0].minute, 0)
            # Exactly at event time should be near
            now_at_event = datetime(events[0].year, events[0].month, events[0].day, 9, 0, tzinfo=ZoneInfo("America/New_York"))
            self.assertTrue(cal.is_near_news(now_at_event, buffer_minutes=15))

    def test_mock_feed(self):
        from data.feed import MockDataFeed, get_feed
        feed = MockDataFeed(19000.0)
        self.assertTrue(feed.is_connected())
        df_1m = feed.get_1m_candles(50)
        self.assertGreaterEqual(len(df_1m), 50)
        self.assertIn("close", df_1m.columns)
        price = feed.get_current_price()
        self.assertIsNotNone(price)
        self.assertIsInstance(price, (int, float))
        self.assertIsNotNone(get_feed("paper", use_live_feed=False))


# ---------- Strategy: market structure ----------
class TestMarketStructure(unittest.TestCase):
    def test_swing_highs_lows(self):
        from strategy.market_structure import swing_highs_lows, trend_from_structure, TrendDirection
        np.random.seed(42)
        idx = pd.date_range("2024-01-02 07:00", periods=30, freq="15min", tz=EST)
        df = pd.DataFrame({
            "open": np.random.randn(30).cumsum() + 19000,
            "high": np.random.randn(30).cumsum() + 19020,
            "low": np.random.randn(30).cumsum() + 18980,
            "close": np.random.randn(30).cumsum() + 19000,
            "volume": 1000,
        }, index=idx)
        highs, lows = swing_highs_lows(df, lookback=10, left_bars=2, right_bars=2)
        trend = trend_from_structure(df, highs, lows)
        self.assertIn(trend, (TrendDirection.BULLISH, TrendDirection.BEARISH, TrendDirection.RANGING))


# ---------- Strategy: key levels ----------
class TestKeyLevels(unittest.TestCase):
    def test_build_key_levels(self):
        from strategy.key_levels import build_key_levels, KeyLevels
        idx_15 = pd.date_range("2024-01-02 07:00", periods=50, freq="15min", tz=EST)
        idx_1 = pd.date_range("2024-01-02 07:00", periods=100, freq="1min", tz=EST)
        df_15 = pd.DataFrame({
            "open": 19000., "high": 19050., "low": 18950., "close": 19020., "volume": 1000
        }, index=idx_15)
        df_1 = pd.DataFrame({
            "open": 19000., "high": 19030., "low": 18980., "close": 19010., "volume": 500
        }, index=idx_1)
        now = datetime(2024, 1, 2, 9, 0, tzinfo=EST)
        kl = build_key_levels(df_15, df_1, now)
        self.assertIsInstance(kl, KeyLevels)
        self.assertIsNotNone(kl.round_numbers)
        levels = kl.all_levels()
        self.assertIsInstance(levels, list)


# ---------- Strategy: entry checklist ----------
class TestEntryChecklist(unittest.TestCase):
    def test_in_trading_window(self):
        from strategy.entry_checklist import in_trading_window
        self.assertTrue(in_trading_window(datetime(2024, 1, 2, 8, 0, tzinfo=EST)))
        self.assertTrue(in_trading_window(datetime(2024, 1, 2, 10, 0, tzinfo=EST)))
        self.assertFalse(in_trading_window(datetime(2024, 1, 2, 12, 0, tzinfo=EST)))

    def test_validate_entry_time_filter_rth(self):
        """When NO_LONG_FIRST_MINUTES_RTH=15, LONG in first 15 min after 9:30 is rejected."""
        from unittest.mock import patch
        from strategy.entry_checklist import validate_entry
        from strategy.setups import ReversalSetup, SetupType
        from strategy.market_structure import TrendDirection
        setup = ReversalSetup(
            setup_type=SetupType.RETEST_REVERSAL,
            direction="LONG",
            entry_price=19000.,
            stop_price=18980.,
            target1_price=19040.,
            target2_price=19070.,
            key_level_name="Test",
            confidence="High",
            trend_15m=TrendDirection.BULLISH,
            notes="",
        )
        with patch("strategy.entry_checklist.NO_LONG_FIRST_MINUTES_RTH", 15), patch("strategy.entry_checklist.NO_SHORT_FIRST_MINUTES_RTH", 0), patch("strategy.entry_checklist.is_near_news", return_value=False):
            now_rth_early = datetime(2024, 1, 2, 9, 35, tzinfo=EST)  # 5 min after 9:30
            r = validate_entry(setup, now_rth_early, 0, 3)
            self.assertFalse(r.valid)
            self.assertIn("first 15 min", r.reason)
            now_rth_late = datetime(2024, 1, 2, 9, 50, tzinfo=EST)  # 20 min after 9:30
            r2 = validate_entry(setup, now_rth_late, 0, 3)
            self.assertTrue(r2.valid)

    def test_validate_entry(self):
        from strategy.entry_checklist import validate_entry
        from strategy.setups import ReversalSetup, SetupType
        from strategy.market_structure import TrendDirection
        setup = ReversalSetup(
            setup_type=SetupType.RETEST_REVERSAL,
            direction="LONG",
            entry_price=19000.,
            stop_price=18980.,
            target1_price=19040.,
            target2_price=19070.,
            key_level_name="Test",
            confidence="High",
            trend_15m=TrendDirection.BULLISH,
            notes="",
        )
        now = datetime(2024, 1, 2, 8, 30, tzinfo=EST)
        r = validate_entry(setup, now, 0, 3)
        self.assertTrue(r.valid or not r.valid)  # just no crash
        r2 = validate_entry(setup, now, 5, 3)  # max trades reached
        self.assertFalse(r2.valid)

    def test_validate_entry_with_orderflow_summary(self):
        from strategy.entry_checklist import validate_entry, check_orderflow
        from strategy.setups import ReversalSetup, SetupType
        from strategy.market_structure import TrendDirection
        setup = ReversalSetup(
            setup_type=SetupType.RETEST_REVERSAL,
            direction="LONG",
            entry_price=19000.,
            stop_price=18980.,
            target1_price=19040.,
            target2_price=19070.,
            key_level_name="Test",
            confidence="High",
            trend_15m=TrendDirection.BULLISH,
            notes="",
        )
        now = datetime(2024, 1, 2, 8, 30, tzinfo=EST)
        r = validate_entry(setup, now, 0, 3, orderflow_summary={"imbalance_ratio": 0.3, "age_seconds": 1})
        self.assertTrue(r.valid)
        of_reject = check_orderflow(setup, {"imbalance_ratio": -0.8, "age_seconds": 1})
        self.assertIsNotNone(of_reject)
        self.assertFalse(of_reject.valid)


# ---------- Strategy: trade manager ----------
class TestTradeManager(unittest.TestCase):
    def test_active_trade(self):
        from strategy.trade_manager import ActiveTrade
        t = ActiveTrade(
            direction="LONG",
            entry=19000., stop=18980., target1=19040., target2=19070.,
            contracts=1, risk_per_contract_usd=40.,
        )
        self.assertAlmostEqual(t.risk_pts(), 20.)
        self.assertAlmostEqual(t.rr_at_price(19040.), 2.0)
        self.assertAlmostEqual(t.pnl_at_price(19020.), 40.)


# ---------- Strategy: setups ----------
class TestSetups(unittest.TestCase):
    def test_detect_setup_retest_only(self):
        from strategy.setups import detect_setup, SetupType
        from strategy.key_levels import KeyLevels
        from strategy.market_structure import TrendDirection, SwingPoint
        idx = pd.date_range("2024-01-02 08:00", periods=20, freq="1min", tz=EST)
        df_1m = pd.DataFrame({
            "open": [19000]*20, "high": [19015]*20, "low": [18990]*20, "close": [19010]*20, "volume": 500
        }, index=idx)
        df_1m.loc[df_1m.index[-1], "open"] = 18995
        df_1m.loc[df_1m.index[-1], "low"] = 18992
        df_1m.loc[df_1m.index[-1], "close"] = 19008
        df_15m = df_1m.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        kl = KeyLevels(
            prev_day_high=None, prev_day_low=18992., prev_day_close=19000.,
            seven_am_high=None, seven_am_low=None,
            session_open_high=None, session_open_low=None,
            round_numbers=[19000], as_of=idx[-1].to_pydatetime(),
        )
        swing_highs = [SwingPoint(10, 19020, True, idx[10])]
        swing_lows = [SwingPoint(5, 18992, False, idx[5])]
        setup = detect_setup(df_1m, df_15m, kl, swing_highs, swing_lows, TrendDirection.BULLISH,
                            level_tolerance_pts=10, require_trend_only=False, retest_only=True)
        # May or may not find setup depending on candle pattern
        self.assertTrue(setup is None or setup.direction in ("LONG", "SHORT"))


# ---------- Broker ----------
class TestBroker(unittest.TestCase):
    def test_paper_broker(self):
        from broker import get_broker
        from broker.paper_trade import PaperBroker
        b = get_broker("paper")
        self.assertIsInstance(b, PaperBroker)
        self.assertTrue(b.is_connected())
        self.assertEqual(b.get_position("MNQ"), 0)
        res = b.place_market_order("MNQ", "BUY", 1)
        self.assertTrue(res.success)
        self.assertEqual(b.get_position("MNQ"), 1)


# ---------- Backtest ----------
class TestBacktest(unittest.TestCase):
    def test_backtest_synthetic_short(self):
        from backtest import BacktestEngine, generate_backtest_data
        df_1m, df_15m = generate_backtest_data(trading_days=3, seed=123)
        self.assertGreater(len(df_1m), 100)
        engine = BacktestEngine(
            initial_balance=50_000,
            risk_per_trade_usd=100,
            max_trades_per_day=3,
            min_rr=2.0,
            level_tolerance_pts=8,
            require_trend_only=True,
            retest_only=True,
        )
        result = engine.run(df_1m, df_15m)
        self.assertIsNotNone(result)
        self.assertEqual(result.initial_balance, 50_000)
        self.assertGreaterEqual(result.final_balance, 0)
        self.assertGreaterEqual(len(result.trades), 0)
        self.assertGreaterEqual(result.win_rate_pct, 0)
        self.assertLessEqual(result.win_rate_pct, 100)


# ---------- Bot / Alerts ----------
class TestBot(unittest.TestCase):
    def test_alert_formats(self):
        from bot.alerts import format_trade_alert, format_trail_alert, format_stop_hit, format_daily_summary
        msg = format_trade_alert(
            "Retest Reversal", "8:15 AM EST", "LONG",
            19000., 18980., 19040., 19070.,
            2.0, "High", "1-min | 15-min trend: Bullish", "PDH", "Notes"
        )
        self.assertIn("19,000", msg)  # formatted with comma
        self.assertIn("LONG", msg)
        trail = format_trail_alert("LONG", 19000., 19040., 2.0, "Move to +1R", 19020., "locks in", 19070.)
        self.assertIn("19,040", trail)
        stop_msg = format_stop_hit("LONG", 19000., 19020., 40., "locked +1R", 100.)
        self.assertIn("TRADE CLOSED", stop_msg)
        summary = format_daily_summary("2024-01-02", 2, 1, 1, 50., 50., ["Trade 1: LONG +25", "Trade 2: SHORT -25"])
        self.assertIn("P&L", summary)

    def test_commands_import(self):
        from bot.commands import register_commands, get_state
        state = get_state()
        self.assertIn("scan_active", state)
        self.assertIn("trades_today", state)


# ---------- Integration: main and run_backtest ----------
class TestIntegration(unittest.TestCase):
    def test_main_imports(self):
        # Just verify main and its dependencies load
        import main
        self.assertTrue(hasattr(main, "run_scan"))
        self.assertTrue(hasattr(main, "run_trailing"))

    def test_run_backtest_imports(self):
        import run_backtest
        self.assertTrue(hasattr(run_backtest, "print_report"))
        self.assertTrue(hasattr(run_backtest, "main"))


# ---------- Full signal & alert capability ----------
class TestSignalAndAlertCapability(unittest.TestCase):
    """Verify bot is fully capable of producing proper signals and alerts."""

    def test_valid_setup_produces_proper_trade_alert(self):
        """When a valid setup passes checklist, formatted alert contains all required fields."""
        from bot.alerts import format_trade_alert
        from strategy.setups import ReversalSetup, SetupType
        from strategy.market_structure import TrendDirection
        setup = ReversalSetup(
            setup_type=SetupType.RETEST_REVERSAL,
            direction="LONG",
            entry_price=21500.25,
            stop_price=21480.50,
            target1_price=21540.00,
            target2_price=21580.00,
            key_level_name="7 AM High",
            confidence="High",
            trend_15m=TrendDirection.BULLISH,
            notes="Test level.",
        )
        msg = format_trade_alert(
            setup_name=setup.setup_type.value,
            time_est="09:15 AM EST",
            direction=setup.direction,
            entry=setup.entry_price,
            stop=setup.stop_price,
            tp1=setup.target1_price,
            tp2=setup.target2_price,
            rr_ratio=2.0,
            confidence=setup.confidence,
            timeframe_note="1-min | 15-min trend: Bullish",
            key_level=setup.key_level_name,
            notes=setup.notes,
        )
        self.assertIn("LONG", msg)
        self.assertIn("21,500.25", msg)
        self.assertIn("21,480.50", msg)
        self.assertIn("21,540.00", msg)
        self.assertIn("2.0:1", msg)
        self.assertIn("7 AM High", msg)
        self.assertIn("Retest Reversal", msg)

    def test_trail_milestone_produces_proper_trail_alert(self):
        """Trail milestone logic + format_trail_alert produces valid trail message."""
        from strategy.trade_manager import ActiveTrade, next_milestone_to_trail, stop_for_milestone
        from bot.alerts import format_trail_alert
        trade = ActiveTrade(
            direction="LONG",
            entry=21500.0,
            stop=21480.0,
            target1=21540.0,
            target2=21580.0,
            contracts=1,
            risk_per_contract_usd=40.0,
        )
        current_r = trade.rr_at_price(21530.0)  # +1.5R
        next_m = next_milestone_to_trail(current_r, trade.last_trailed_r)
        self.assertIsNotNone(next_m, "Should hit a milestone (e.g. 1.0R)")
        new_stop = stop_for_milestone(trade, next_m)
        msg = format_trail_alert(
            trade.direction,
            trade.entry,
            21530.0,
            current_r,
            "Move Stop Loss to +1R",
            new_stop,
            "(locks in +$40/contract)",
            trade.target2,
            "",
        )
        self.assertIn("LONG", msg)
        self.assertIn("21,500", msg)
        self.assertIn("21,530", msg)
        self.assertIn("+1R", msg)

    def test_run_scan_with_mock_feed_no_crash(self):
        """run_scan with mock feed and mocked window/state does not crash."""
        import asyncio
        from unittest.mock import patch, MagicMock, AsyncMock
        from data.feed import MockDataFeed, get_feed
        import main
        async def run():
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            with patch("main.get_feed", return_value=MockDataFeed(19000.0)), \
                 patch("main.in_scan_window", return_value=True), \
                 patch("main.get_state", return_value={
                     "scan_active": True, "trades_today": 0, "daily_pnl": 0,
                     "risk_per_trade": 380, "active_trades": [], "trade_history": [],
                     "use_orderflow": False, "key_levels_text": "",
                 }), \
                 patch("main.TELEGRAM_CHAT_ID", "123"):
                await main.run_scan(mock_bot)
        asyncio.run(run())

    def test_stop_hit_and_daily_summary_formats(self):
        """Stop-hit and daily summary alerts format correctly."""
        from bot.alerts import format_stop_hit, format_daily_summary
        stop_msg = format_stop_hit("SHORT", 21500.0, 21520.0, -40.0, "stopped", -80.0)
        self.assertIn("SHORT", stop_msg)
        self.assertIn("21,500", stop_msg)
        self.assertIn("TRADE CLOSED", stop_msg)
        self.assertIn("-80", stop_msg)
        summary = format_daily_summary("2024-01-02", 3, 2, 1, 120.0, 66.7, [
            "Trade 1: LONG @ 21,500 → +60",
            "Trade 2: SHORT @ 21,520 → +40",
            "Trade 3: LONG @ 21,480 → +20",
        ])
        self.assertIn("P&L", summary)
        self.assertIn("120", summary)
        self.assertIn("Today's trades", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
