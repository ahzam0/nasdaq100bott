"""
Abstract base strategy with NASDAQ market hours awareness.
Auto-pause first 30 min, reduce size during lunch, boost during Power Hour.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import time
from typing import Optional

import pandas as pd

from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# NASDAQ session windows (ET)
PREMARKET_START = time(4, 0)
REGULAR_START = time(9, 30)
FIRST_30_END = time(10, 0)
LUNCH_START = time(12, 0)
LUNCH_END = time(13, 30)
POWER_HOUR_START = time(15, 0)
REGULAR_END = time(16, 0)
AFTER_HOURS_END = time(20, 0)

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """All strategies inherit this; NASDAQ hours and earnings awareness."""

    def __init__(
        self,
        no_entries_first_min: int = 30,
        lunch_reduce_pct: float = 0.5,
        power_hour_size_mult: float = 2.0,
    ):
        self.no_entries_first_min = no_entries_first_min
        self.lunch_reduce_pct = lunch_reduce_pct
        self.power_hour_size_mult = power_hour_size_mult

    def session_filter(self, ts: pd.DatetimeIndex) -> pd.Series:
        """1.0 = full size, 0.0 = no entry, 0.5 = lunch reduce, 2.0 = power hour boost."""
        if ts is None or len(ts) == 0:
            return pd.Series(dtype=float)
        times = ts.to_series().dt.tz_convert(ET).dt.time
        out = pd.Series(1.0, index=ts)
        # No entry first 30 min
        out[(times >= REGULAR_START) & (times < FIRST_30_END)] = 0.0
        # Lunch reduce
        out[(times >= LUNCH_START) & (times < LUNCH_END)] = self.lunch_reduce_pct
        # Power hour boost
        out[(times >= POWER_HOUR_START) & (times < REGULAR_END)] = self.power_hour_size_mult
        return out

    def size_multiplier(self, ts: pd.DatetimeIndex) -> pd.Series:
        return self.session_filter(ts)

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame, symbol: str) -> pd.Series:
        """Return series of -1, 0, 1 (short, flat, long) aligned to df.index."""
        pass

    def check_earnings_before_entry(self, symbol: str, as_of: pd.Timestamp) -> bool:
        """Override: return True if entry allowed (not within earnings blackout)."""
        from data.calendar import is_earnings_soon
        return not is_earnings_soon(symbol, within_days=2, as_of=as_of.date() if hasattr(as_of, "date") else as_of)
