"""
Strategy 1 — NASDAQ Opening Range Breakout (ORB).
Daily proxy: breakout of previous day high/low with trend and volume confirmation.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from nas100_elite.config import ORB_SL_BUFFER_POINTS, SL_POINTS_MIN, SL_POINTS_MAX


def _atr_points(high: pd.Series, low: pd.Series, period: int = 14) -> pd.Series:
    return (high - low).rolling(period).mean()


def generate_orb_entries(
    df: pd.DataFrame,
    atr_min_points: float = 15.0,
    min_bars_apart: int = 2,
) -> List[Tuple[int, str, float, float, float, float, float, float, str, int]]:
    """
    Returns list of (bar_i, direction, entry, sl, tp1, tp2, trail_pts, risk_pct, setup_type, confluence_score).
    Daily proxy: ORB = previous day high/low. Breakout = close above prev high (BUY) or below prev low (SELL).
    """
    if df is None or len(df) < 30:
        return []
    entries = []
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    open_ = df["open"].values
    last_entry = -100
    ema200 = df["close"].ewm(span=200, adjust=False).mean().values if len(df) >= 200 else close
    atr = _atr_points(df["high"], df["low"]).values
    volume = df["volume"].values if "volume" in df.columns else np.ones(len(df))
    vol_ma = pd.Series(volume).rolling(20).mean().values if "volume" in df.columns else volume

    for i in range(2, len(df) - 1):
        if i - last_entry < min_bars_apart:
            continue
        prev_high = high[i - 1]
        prev_low = low[i - 1]
        prev_open = open_[i - 1]
        prev_close = close[i - 1]
        range_size = prev_high - prev_low
        if range_size <= 0:
            continue
        atr_i = atr[i] if not np.isnan(atr[i]) and atr[i] > 0 else range_size
        if atr_i < atr_min_points:
            continue
        sl_buffer = min(ORB_SL_BUFFER_POINTS, range_size * 0.1)
        d1_bull = close[i] > ema200[i] if not np.isnan(ema200[i]) else True
        d1_bear = close[i] < ema200[i] if not np.isnan(ema200[i]) else True
        vol_ok = volume[i] >= vol_ma[i - 1] * 0.8 if not np.isnan(vol_ma[i - 1]) else True
        rr_ok = True

        if close[i] > prev_high and d1_bull and vol_ok:
            entry = float(close[i])
            sl = prev_low - sl_buffer
            sl_pts = entry - sl
            if SL_POINTS_MIN <= sl_pts <= SL_POINTS_MAX:
                tp1 = entry + range_size
                tp2 = entry + range_size * 2
                entries.append((i, "BUY", entry, sl, tp1, tp2, 30.0, 1.5, "ORB", 6))
                last_entry = i
        elif close[i] < prev_low and d1_bear and vol_ok:
            entry = float(close[i])
            sl = prev_high + sl_buffer
            sl_pts = sl - entry
            if SL_POINTS_MIN <= sl_pts <= SL_POINTS_MAX:
                tp1 = entry - range_size
                tp2 = entry - range_size * 2
                entries.append((i, "SELL", entry, sl, tp1, tp2, 30.0, 1.5, "ORB", 6))
                last_entry = i
    return entries


class ORBStrategy:
    def __init__(self, atr_min_points: float = 15.0, min_bars_apart: int = 2):
        self.atr_min_points = atr_min_points
        self.min_bars_apart = min_bars_apart

    def generate_entries(self, df: pd.DataFrame) -> List[Tuple[int, str, float, float, float, float, float, float, str, int]]:
        return generate_orb_entries(df, self.atr_min_points, self.min_bars_apart)
