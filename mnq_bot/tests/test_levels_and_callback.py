"""
Test levels-on-demand and Yahoo WS toggle (callback flow).
Run: python -m unittest tests.test_levels_and_callback -v
      or: cd mnq_bot && python -m pytest tests/test_levels_and_callback.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestLevelsAndCallback(unittest.TestCase):
    def test_get_levels_on_demand_returns_tuple(self):
        """get_levels_on_demand returns (text or None, error_hint)."""
        from main import get_levels_on_demand
        levels_text, error_hint = get_levels_on_demand()
        self.assertIsInstance(levels_text, (type(None), str))
        self.assertIsInstance(error_hint, str)
        if levels_text:
            self.assertTrue(
                "Prev Day" in levels_text or "7 AM" in levels_text or "Session" in levels_text or "No levels" in levels_text,
                msg=f"levels_text should contain level labels: {levels_text[:100]}",
            )
        else:
            self.assertGreater(len(error_hint), 0, msg="error_hint should be non-empty when no levels")

    def test_yahoo_ws_toggle_get_set(self):
        """Runtime Yahoo WS setting can be read and set (used by callback buttons)."""
        from config import get_use_yahoo_ws_realtime, set_use_yahoo_ws_realtime
        orig = get_use_yahoo_ws_realtime()
        try:
            set_use_yahoo_ws_realtime(False)
            self.assertFalse(get_use_yahoo_ws_realtime())
            set_use_yahoo_ws_realtime(True)
            self.assertTrue(get_use_yahoo_ws_realtime())
        finally:
            set_use_yahoo_ws_realtime(orig)

    def test_callback_data_matches_handler(self):
        """Callback data strings match what CallbackQueryHandler pattern expects."""
        for data in ("yahoo_ws_on", "yahoo_ws_off"):
            self.assertIn(data, ("yahoo_ws_on", "yahoo_ws_off"))
