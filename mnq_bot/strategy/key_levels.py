"""
Key level detection: previous day H/L/C, 7AM candle, session opening range, round numbers.
All levels in price (points).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time

import pandas as pd

from config import ROUND_NUMBER_STEP, RTH_START, SESSION_OPENING_RANGE_MINUTES

logger = logging.getLogger(__name__)


@dataclass
class KeyLevels:
    """Key price levels for the session (EST day)."""
    prev_day_high: float | None
    prev_day_low: float | None
    prev_day_close: float | None
    seven_am_high: float | None
    seven_am_low: float | None
    session_open_high: float | None  # First 5 min of RTH
    session_open_low: float | None
    round_numbers: list[float]
    as_of: datetime

    def all_levels(self) -> list[float]:
        """Flat list of all defined numeric levels for proximity checks."""
        out = []
        for v in (
            self.prev_day_high, self.prev_day_low, self.prev_day_close,
            self.seven_am_high, self.seven_am_low,
            self.session_open_high, self.session_open_low
        ):
            if v is not None:
                out.append(v)
        out.extend(self.round_numbers)
        return sorted(set(out))

    def nearest_level(self, price: float, max_points_away: float = 20.0) -> tuple[float | None, str]:
        """
        Return (level, description) for the nearest key level to price within max_points_away.
        """
        best = None
        best_dist = max_points_away
        label = ""
        if self.prev_day_high is not None and abs(price - self.prev_day_high) < best_dist:
            best_dist = abs(price - self.prev_day_high)
            best = self.prev_day_high
            label = "Previous Day High"
        if self.prev_day_low is not None and abs(price - self.prev_day_low) < best_dist:
            best_dist = abs(price - self.prev_day_low)
            best = self.prev_day_low
            label = "Previous Day Low"
        if self.prev_day_close is not None and abs(price - self.prev_day_close) < best_dist:
            best_dist = abs(price - self.prev_day_close)
            best = self.prev_day_close
            label = "Previous Day Close"
        if self.seven_am_high is not None and abs(price - self.seven_am_high) < best_dist:
            best_dist = abs(price - self.seven_am_high)
            best = self.seven_am_high
            label = "7 AM Candle High"
        if self.seven_am_low is not None and abs(price - self.seven_am_low) < best_dist:
            best_dist = abs(price - self.seven_am_low)
            best = self.seven_am_low
            label = "7 AM Candle Low"
        if self.session_open_high is not None and abs(price - self.session_open_high) < best_dist:
            best_dist = abs(price - self.session_open_high)
            best = self.session_open_high
            label = "Session Opening Range High"
        if self.session_open_low is not None and abs(price - self.session_open_low) < best_dist:
            best_dist = abs(price - self.session_open_low)
            best = self.session_open_low
            label = "Session Opening Range Low"
        for r in self.round_numbers:
            if abs(price - r) < best_dist:
                best_dist = abs(price - r)
                best = r
                label = f"Round number {r}"
        return (best, label) if best is not None else (None, "")


def _round_numbers_near(price: float, step: int = ROUND_NUMBER_STEP, count: int = 6) -> list[float]:
    """Round numbers around current price (e.g. 19000, 19050, 19100)."""
    base = (price // step) * step
    out = []
    for i in range(-count // 2, count // 2 + 1):
        out.append(base + i * step)
    return sorted(set(out))


def compute_prev_day_hlc(df_15m: pd.DataFrame, current_est: datetime) -> tuple[float | None, float | None, float | None]:
    """
    From 15m dataframe (index = datetime), compute previous session day H, L, C.
    Assumes index is timezone-aware or naive UTC; we treat dates by EST day.
    """
    if df_15m.empty or len(df_15m) < 2:
        return None, None, None
    # Use last available date as reference; prev day = day before that
    try:
        idx = df_15m.index
        if hasattr(idx, "tz_localize"):
            # Normalize to EST for day split if needed
            if idx.tz is None:
                idx = idx.tz_localize("UTC").tz_convert("America/New_York")
            else:
                idx = idx.tz_convert("America/New_York")
        last_date = idx[-1].date() if hasattr(idx[-1], "date") else idx[-1]
        from datetime import timedelta
        prev_date = last_date - timedelta(days=1) if hasattr(last_date, "day") else last_date
        # Filter rows that fall on prev_date (by EST date)
        if hasattr(idx, "date"):
            mask = idx.date == prev_date
        else:
            mask = pd.Series(idx).dt.date == prev_date
        day_df = df_15m.loc[mask]
        if day_df.empty:
            return None, None, None
        high = float(day_df["high"].max())
        low = float(day_df["low"].min())
        close = float(day_df["close"].iloc[-1])
        return high, low, close
    except Exception as e:
        logger.warning("compute_prev_day_hlc error: %s", e)
        return None, None, None


def compute_7am_levels(df_15m: pd.DataFrame, current_est: datetime) -> tuple[float | None, float | None]:
    """7 AM EST candle high and low. 7:00 bar = 7:00–7:15 EST."""
    if df_15m.empty:
        return None, None
    try:
        idx = df_15m.index
        if idx.tz is None:
            idx = pd.DatetimeIndex(idx).tz_localize("UTC").tz_convert("America/New_York")
        else:
            idx = idx.tz_convert("America/New_York")
        # Today's 7 AM bar: hour=7, minute in [0,15)
        today = current_est.date() if hasattr(current_est, "date") else current_est
        mask = (idx.hour == 7) & (idx.minute < 15)
        if hasattr(idx, "date"):
            mask = mask & (idx.date == today)
        else:
            mask = mask & (pd.Series(idx).dt.date == today)
        bars = df_15m.loc[mask]
        if bars.empty:
            return None, None
        return float(bars["high"].max()), float(bars["low"].min())
    except Exception as e:
        logger.warning("compute_7am_levels error: %s", e)
        return None, None


def compute_session_opening_range(
    df_1m: pd.DataFrame,
    rth_start: str = RTH_START,
    range_minutes: int = SESSION_OPENING_RANGE_MINUTES,
) -> tuple[float | None, float | None]:
    """First N minutes of RTH (e.g. 9:30–9:35) high and low."""
    if df_1m.empty:
        return None, None
    try:
        idx = df_1m.index
        if idx.tz is None:
            idx = pd.DatetimeIndex(idx).tz_localize("UTC").tz_convert("America/New_York")
        else:
            idx = idx.tz_convert("America/New_York")
        hour, minute = int(rth_start.split(":")[0]), int(rth_start.split(":")[1])
        # Bars from 9:30 to 9:30+range_minutes
        mask = (idx.hour == hour) & (idx.minute >= minute) & (idx.minute < minute + range_minutes)
        bars = df_1m.loc[mask]
        if bars.empty:
            return None, None
        return float(bars["high"].max()), float(bars["low"].min())
    except Exception as e:
        logger.warning("compute_session_opening_range error: %s", e)
        return None, None


def build_key_levels(
    df_15m: pd.DataFrame,
    df_1m: pd.DataFrame,
    current_est: datetime,
    round_step: int = ROUND_NUMBER_STEP,
) -> KeyLevels:
    """Build KeyLevels from 15m and 1m data."""
    prev_h, prev_l, prev_c = compute_prev_day_hlc(df_15m, current_est)
    seven_h, seven_l = compute_7am_levels(df_15m, current_est)
    session_h, session_l = compute_session_opening_range(df_1m)
    current_price = float(df_1m["close"].iloc[-1]) if not df_1m.empty else 19000.0
    rounds = _round_numbers_near(current_price, round_step)
    return KeyLevels(
        prev_day_high=prev_h,
        prev_day_low=prev_l,
        prev_day_close=prev_c,
        seven_am_high=seven_h,
        seven_am_low=seven_l,
        session_open_high=session_h,
        session_open_low=session_l,
        round_numbers=rounds,
        as_of=current_est,
    )
