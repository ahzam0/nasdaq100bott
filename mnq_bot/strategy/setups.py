"""
Setup identification: Retest Reversal and Failed Breakout Reversal.
Uses 1-min reversal candlestick patterns at key zones.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from strategy.key_levels import KeyLevels
from strategy.market_structure import (
    SwingPoint,
    TrendDirection,
    get_last_swing_high,
    get_last_swing_low,
)

logger = logging.getLogger(__name__)


class SetupType(str, Enum):
    RETEST_REVERSAL = "Retest Reversal"
    FAILED_BREAKOUT_REVERSAL = "Failed Breakout Reversal"
    NONE = "None"


@dataclass
class ReversalSetup:
    setup_type: SetupType
    direction: str  # "LONG" | "SHORT"
    entry_price: float
    stop_price: float
    target1_price: float
    target2_price: float
    key_level_name: str
    confidence: str  # "High" | "Medium" | "Low"
    trend_15m: TrendDirection
    notes: str


def _is_bullish_engulfing(row: pd.Series, prev: pd.Series) -> bool:
    """Current candle opens below prev close and closes above prev open, body engulfs prev."""
    if row["close"] <= row["open"] or prev["close"] <= prev["open"]:
        return False
    return row["open"] < prev["close"] and row["close"] > prev["open"] and row["open"] <= prev["low"]


def _is_bearish_engulfing(row: pd.Series, prev: pd.Series) -> bool:
    if row["open"] <= row["close"] or prev["open"] <= prev["close"]:
        return False
    return row["open"] > prev["close"] and row["close"] < prev["open"] and row["open"] >= prev["high"]


def _is_pin_bar_bull(low: float, open_: float, close: float, high: float, body_ratio: float = 0.4) -> bool:
    """Lower wick much larger than body; close in upper half."""
    body = abs(close - open_)
    range_ = high - low
    if range_ <= 0:
        return False
    lower_wick = min(open_, close) - low
    return lower_wick >= body * 2 and body <= range_ * body_ratio and lower_wick >= range_ * 0.5


def _is_pin_bar_bear(high: float, open_: float, close: float, low: float, body_ratio: float = 0.4) -> bool:
    upper_wick = high - max(open_, close)
    body = abs(close - open_)
    range_ = high - low
    if range_ <= 0:
        return False
    return upper_wick >= body * 2 and body <= range_ * body_ratio and upper_wick >= range_ * 0.5


def _near_level(price: float, level: float, tolerance_pts: float = 5.0) -> bool:
    return level is not None and abs(price - level) <= tolerance_pts


def _check_retest_reversal_long(
    df_1m: pd.DataFrame,
    key_levels: KeyLevels,
    swing_lows: list[SwingPoint],
    trend: TrendDirection,
    level_tolerance_pts: float = 8.0,
) -> ReversalSetup | None:
    """Price retested support (e.g. swing low or prev day low), 1m reversal candle formed."""
    if df_1m.empty or len(df_1m) < 3:
        return None
    last = df_1m.iloc[-1]
    prev = df_1m.iloc[-2]
    low = float(last["low"])
    close = float(last["close"])
    open_ = float(last["open"])
    high = float(last["high"])
    # Support levels: prev day low, 7am low, session open low, last swing low
    supports = [
        (key_levels.prev_day_low, "Previous Day Low"),
        (key_levels.seven_am_low, "7 AM Candle Low"),
        (key_levels.session_open_low, "Session Opening Range Low"),
        (get_last_swing_low(swing_lows), "Swing Low"),
    ]
    for level, name in supports:
        if not _near_level(low, level, level_tolerance_pts):
            continue
        if _is_bullish_engulfing(last, prev) or _is_pin_bar_bull(low, open_, close, high):
            sl = (swing_lows[-1].price - 5.0) if swing_lows else low - 15.0
            risk = close - sl
            if risk <= 0:
                continue
            tp1 = close + risk * 2
            tp2 = close + risk * 3.5
            return ReversalSetup(
                setup_type=SetupType.RETEST_REVERSAL,
                direction="LONG",
                entry_price=close,
                stop_price=sl,
                target1_price=tp1,
                target2_price=tp2,
                key_level_name=name,
                confidence="High",
                trend_15m=trend,
                notes="Reversal at support",
            )
    return None


def _check_retest_reversal_short(
    df_1m: pd.DataFrame,
    key_levels: KeyLevels,
    swing_highs: list[SwingPoint],
    trend: TrendDirection,
    level_tolerance_pts: float = 8.0,
) -> ReversalSetup | None:
    if df_1m.empty or len(df_1m) < 3:
        return None
    last = df_1m.iloc[-1]
    prev = df_1m.iloc[-2]
    high = float(last["high"])
    close = float(last["close"])
    open_ = float(last["open"])
    low = float(last["low"])
    resistances = [
        (key_levels.prev_day_high, "Previous Day High"),
        (key_levels.seven_am_high, "7 AM Candle High"),
        (key_levels.session_open_high, "Session Opening Range High"),
        (get_last_swing_high(swing_highs), "Swing High"),
    ]
    for level, name in resistances:
        if level is None:
            continue
        if not _near_level(high, level, level_tolerance_pts):
            continue
        if _is_bearish_engulfing(last, prev) or _is_pin_bar_bear(high, open_, close, low):
            sl = (swing_highs[-1].price + 5.0) if swing_highs else high + 15.0
            risk = sl - close
            if risk <= 0:
                continue
            tp1 = close - risk * 2
            tp2 = close - risk * 3.5
            return ReversalSetup(
                setup_type=SetupType.RETEST_REVERSAL,
                direction="SHORT",
                entry_price=close,
                stop_price=sl,
                target1_price=tp1,
                target2_price=tp2,
                key_level_name=name,
                confidence="High",
                trend_15m=trend,
                notes="Reversal at resistance",
            )
    return None


def _check_failed_breakout_long(
    df_1m: pd.DataFrame,
    key_levels: KeyLevels,
    swing_highs: list[SwingPoint],
) -> ReversalSetup | None:
    """Price broke below support then closed back inside; long reversal."""
    if len(df_1m) < 5:
        return None
    last = df_1m.iloc[-1]
    prev_bars = df_1m.iloc[-5:-1]
    # Resistance that was broken to the downside then reclaimed
    for level in [key_levels.session_open_low, key_levels.seven_am_low, key_levels.prev_day_low]:
        if level is None:
            continue
        # One of prev bars broke below level
        broke_below = (prev_bars["low"] < level).any()
        # Last candle closed above level and is bullish
        closed_above = float(last["close"]) > level and float(last["close"]) > float(last["open"])
        if broke_below and closed_above:
            sl = float(last["low"]) - 10.0
            if swing_highs:
                sl = min(sl, swing_highs[-1].price - 5.0)
            risk = float(last["close"]) - sl
            if risk <= 0:
                continue
            return ReversalSetup(
                setup_type=SetupType.FAILED_BREAKOUT_REVERSAL,
                direction="LONG",
                entry_price=float(last["close"]),
                stop_price=sl,
                target1_price=float(last["close"]) + risk * 2,
                target2_price=float(last["close"]) + risk * 3.5,
                key_level_name="Failed breakdown",
                confidence="High",
                trend_15m=TrendDirection.RANGING,
                notes="Price failed below support and closed back inside",
            )
    return None


def _check_failed_breakout_short(
    df_1m: pd.DataFrame,
    key_levels: KeyLevels,
    swing_lows: list[SwingPoint],
) -> ReversalSetup | None:
    if len(df_1m) < 5:
        return None
    last = df_1m.iloc[-1]
    prev_bars = df_1m.iloc[-5:-1]
    for level in [key_levels.session_open_high, key_levels.seven_am_high, key_levels.prev_day_high]:
        if level is None:
            continue
        broke_above = (prev_bars["high"] > level).any()
        closed_below = float(last["close"]) < level and float(last["close"]) < float(last["open"])
        if broke_above and closed_below:
            sl = float(last["high"]) + 10.0
            if swing_lows:
                sl = max(sl, swing_lows[-1].price + 5.0)
            risk = sl - float(last["close"])
            if risk <= 0:
                continue
            return ReversalSetup(
                setup_type=SetupType.FAILED_BREAKOUT_REVERSAL,
                direction="SHORT",
                entry_price=float(last["close"]),
                stop_price=sl,
                target1_price=float(last["close"]) - risk * 2,
                target2_price=float(last["close"]) - risk * 3.5,
                key_level_name="Failed breakout",
                confidence="High",
                trend_15m=TrendDirection.RANGING,
                notes="Price failed above resistance and closed back inside",
            )
    return None


def detect_setup(
    df_1m: pd.DataFrame,
    df_15m: pd.DataFrame,
    key_levels: KeyLevels,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    trend: TrendDirection,
    level_tolerance_pts: float = 8.0,
    require_trend_only: bool = False,
    retest_only: bool = False,
    min_body_pts: float = 0.0,
) -> ReversalSetup | None:
    """
    Check for Retest Reversal or Failed Breakout Reversal. Returns first valid setup or None.
    require_trend_only: if True, only take trades when 15m trend is Bullish or Bearish (not Ranging).
    retest_only: if True, only take Retest Reversal (no Failed Breakout).
    min_body_pts: require reversal candle body >= this (skip dojis).
    """
    if require_trend_only and trend == TrendDirection.RANGING:
        return None
    if min_body_pts > 0 and not df_1m.empty:
        last = df_1m.iloc[-1]
        body = abs(float(last["close"]) - float(last["open"]))
        if body < min_body_pts:
            return None
    if trend in (TrendDirection.BULLISH, TrendDirection.RANGING):
        s = _check_retest_reversal_long(df_1m, key_levels, swing_lows, trend, level_tolerance_pts)
        if s is not None:
            return s
        if not retest_only:
            s = _check_failed_breakout_long(df_1m, key_levels, swing_highs)
            if s is not None:
                return s
    if trend in (TrendDirection.BEARISH, TrendDirection.RANGING):
        s = _check_retest_reversal_short(df_1m, key_levels, swing_highs, trend, level_tolerance_pts)
        if s is not None:
            return s
        if not retest_only:
            s = _check_failed_breakout_short(df_1m, key_levels, swing_lows)
            if s is not None:
                return s
    return None
