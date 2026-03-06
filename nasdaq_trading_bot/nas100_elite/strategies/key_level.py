"""
Strategy 3 — NASDAQ Key Level Reversal (PDH, PDL, round numbers).
Daily proxy: rejection at previous day high/low or round number; RSI divergence optional.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from nas100_elite.config import KEY_LEVEL_SL_BEYOND_POINTS, SL_POINTS_MIN, SL_POINTS_MAX


def _round_levels(price: float, step: float = 500.0) -> Tuple[float, float]:
    low = (price // step) * step
    high = low + step
    return low, high


def generate_key_level_entries(
    df: pd.DataFrame,
    min_bars_apart: int = 2,
    tp1_min_points: float = 50.0,
) -> List[Tuple[int, str, float, float, float, float, float, float, str, int]]:
    """
    Key levels: PDH, PDL, round numbers (500 pt steps). Entry on rejection candle at level.
    """
    if df is None or len(df) < 15:
        return []
    entries = []
    open_ = df["open"].values
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    last_entry = -100
    rsi = _rsi(close, 14)

    for i in range(3, len(df) - 1):
        if i - last_entry < min_bars_apart:
            continue
        pdh = high[i - 1]
        pdl = low[i - 1]
        round_lo, round_hi = _round_levels(close[i])
        # Rejection at PDH (bearish reversal)
        if high[i] >= pdh * 0.998 and close[i] < open_[i] and (high[i] - close[i]) > (close[i] - low[i]):
            entry = float(close[i])
            sl = pdh + KEY_LEVEL_SL_BEYOND_POINTS
            sl_pts = sl - entry
            if SL_POINTS_MIN <= sl_pts <= SL_POINTS_MAX:
                tp1 = entry - max(tp1_min_points, sl_pts * 2.5)
                tp2 = entry - sl_pts * 4
                entries.append((i, "SELL", entry, sl, tp1, tp2, 25.0, 1.0, "KeyLevel", 5))
                last_entry = i
        # Rejection at PDL (bullish reversal)
        elif low[i] <= pdl * 1.002 and close[i] > open_[i] and (close[i] - low[i]) > (high[i] - close[i]):
            entry = float(close[i])
            sl = pdl - KEY_LEVEL_SL_BEYOND_POINTS
            sl_pts = entry - sl
            if SL_POINTS_MIN <= sl_pts <= SL_POINTS_MAX:
                tp1 = entry + max(tp1_min_points, sl_pts * 2.5)
                tp2 = entry + sl_pts * 4
                entries.append((i, "BUY", entry, sl, tp1, tp2, 25.0, 1.0, "KeyLevel", 5))
                last_entry = i
    return entries


def _rsi(close: np.ndarray, period: int) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    ag = pd.Series(gain).ewm(span=period, adjust=False).mean().values
    al = pd.Series(loss).ewm(span=period, adjust=False).mean().values
    rs = np.where(al > 1e-12, ag / np.where(al > 1e-12, al, 1.0), 100.0)
    return 100 - (100 / (1 + rs))


class KeyLevelStrategy:
    def __init__(self, min_bars_apart: int = 2, tp1_min_points: float = 50.0):
        self.min_bars_apart = min_bars_apart
        self.tp1_min_points = tp1_min_points

    def generate_entries(self, df: pd.DataFrame) -> List[Tuple[int, str, float, float, float, float, float, float, str, int]]:
        return generate_key_level_entries(df, self.min_bars_apart, self.tp1_min_points)
