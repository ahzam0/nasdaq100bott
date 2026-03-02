"""
Market structure: swing high/low detection, 15-min trend direction.
Indicator-free price action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from config import SWING_LOOKBACK_15M

logger = logging.getLogger(__name__)


class TrendDirection(str, Enum):
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    RANGING = "Ranging"


@dataclass
class SwingPoint:
    index: int  # bar index
    price: float
    is_high: bool
    timestamp: pd.Timestamp


def swing_highs_lows(
    df: pd.DataFrame,
    lookback: int = SWING_LOOKBACK_15M,
    left_bars: int = 2,
    right_bars: int = 2,
) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """
    Detect swing highs and swing lows: high must be highest over left_bars + 1 + right_bars.
    """
    highs: list[SwingPoint] = []
    lows: list[SwingPoint] = []
    n = len(df)
    if n < left_bars + right_bars + 1:
        return highs, lows
    for i in range(left_bars, n - right_bars):
        if i >= n:
            break
        # Swing high: center bar is max of window
        window_high = df["high"].iloc[i - left_bars : i + right_bars + 1]
        if df["high"].iloc[i] == window_high.max():
            ts = df.index[i] if hasattr(df.index[i], "to_pydatetime") else df.index[i]
            highs.append(SwingPoint(i, float(df["high"].iloc[i]), True, ts))
        window_low = df["low"].iloc[i - left_bars : i + right_bars + 1]
        if df["low"].iloc[i] == window_low.min():
            ts = df.index[i] if hasattr(df.index[i], "to_pydatetime") else df.index[i]
            lows.append(SwingPoint(i, float(df["low"].iloc[i]), False, ts))
    # Limit to last lookback bars
    if len(highs) > lookback:
        highs = highs[-lookback:]
    if len(lows) > lookback:
        lows = lows[-lookback:]
    return highs, lows


def trend_from_structure(
    df_15m: pd.DataFrame,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
) -> TrendDirection:
    """
    Higher highs + higher lows = Bullish; lower highs + lower lows = Bearish; else Ranging.
    """
    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return TrendDirection.RANGING
    h1, h2 = swing_highs[-2].price, swing_highs[-1].price
    l1, l2 = swing_lows[-2].price, swing_lows[-1].price
    if h2 > h1 and l2 > l1:
        return TrendDirection.BULLISH
    if h2 < h1 and l2 < l1:
        return TrendDirection.BEARISH
    return TrendDirection.RANGING


def get_last_swing_high(swing_highs: list[SwingPoint]) -> float | None:
    """Price of most recent swing high (for short stop placement)."""
    return swing_highs[-1].price if swing_highs else None


def get_last_swing_low(swing_lows: list[SwingPoint]) -> float | None:
    """Price of most recent swing low (for long stop placement)."""
    return swing_lows[-1].price if swing_lows else None
