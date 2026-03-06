"""
Strategy 2 — NASDAQ Institutional Order Block.
Daily proxy: last bearish candle before 3+ up bars = bullish OB; last bullish before 3+ down = bearish OB.
Pullback into zone + confirmation.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from nas100_elite.config import OB_SL_BEYOND_POINTS, SL_POINTS_MIN, SL_POINTS_MAX


def generate_ob_entries(
    df: pd.DataFrame,
    impulse_bars: int = 3,
    ob_touch_max: int = 2,
    min_bars_apart: int = 3,
) -> List[Tuple[int, str, float, float, float, float, float, float, str, int]]:
    """
    Returns (bar_i, direction, entry, sl, tp1, tp2, trail_pts, risk_pct, setup_type, confluence).
    """
    if df is None or len(df) < 20:
        return []
    entries = []
    open_ = df["open"].values
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    last_entry = -100
    ema200 = df["close"].ewm(span=200, adjust=False).mean().values
    rsi = _rsi(close, 14)

    for i in range(impulse_bars + 5, len(df) - 1):
        if i - last_entry < min_bars_apart:
            continue
        # Bullish OB: candle before impulse was bearish; then 3+ up
        if (close[i - impulse_bars - 1] < open_[i - impulse_bars - 1] and
            all(close[i - k] > open_[i - k] for k in range(1, impulse_bars + 1))):
            ob_high = high[i - impulse_bars - 1]
            ob_low = low[i - impulse_bars - 1]
            if low[i] <= ob_high and high[i] >= ob_low:
                entry = float(close[i])
                sl = ob_low - OB_SL_BEYOND_POINTS[1]
                sl_pts = entry - sl
                if SL_POINTS_MIN <= sl_pts <= SL_POINTS_MAX:
                    swing_high = max(high[i - 5:i])
                    tp1 = min(swing_high, entry + sl_pts * 2)
                    tp2 = entry + sl_pts * 3
                    rsi_ok = 40 <= rsi[i] <= 60 if not np.isnan(rsi[i]) else True
                    d1_ok = close[i] > ema200[i] if not np.isnan(ema200[i]) else True
                    conf = 6 if (rsi_ok and d1_ok) else 5
                    entries.append((i, "BUY", entry, sl, tp1, tp2, 30.0, 1.5, "OB", conf))
                    last_entry = i
        # Bearish OB
        elif (close[i - impulse_bars - 1] > open_[i - impulse_bars - 1] and
              all(close[i - k] < open_[i - k] for k in range(1, impulse_bars + 1))):
            ob_high = high[i - impulse_bars - 1]
            ob_low = low[i - impulse_bars - 1]
            if high[i] >= ob_low and low[i] <= ob_high:
                entry = float(close[i])
                sl = ob_high + OB_SL_BEYOND_POINTS[1]
                sl_pts = sl - entry
                if SL_POINTS_MIN <= sl_pts <= SL_POINTS_MAX:
                    swing_low = min(low[i - 5:i])
                    tp1 = max(swing_low, entry - sl_pts * 2)
                    tp2 = entry - sl_pts * 3
                    rsi_ok = 40 <= rsi[i] <= 60 if not np.isnan(rsi[i]) else True
                    d1_ok = close[i] < ema200[i] if not np.isnan(ema200[i]) else True
                    conf = 6 if (rsi_ok and d1_ok) else 5
                    entries.append((i, "SELL", entry, sl, tp1, tp2, 30.0, 1.5, "OB", conf))
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


class OrderBlockStrategy:
    def __init__(self, impulse_bars: int = 3, ob_touch_max: int = 2, min_bars_apart: int = 3):
        self.impulse_bars = impulse_bars
        self.ob_touch_max = ob_touch_max
        self.min_bars_apart = min_bars_apart

    def generate_entries(self, df: pd.DataFrame) -> List[Tuple[int, str, float, float, float, float, float, float, str, int]]:
        return generate_ob_entries(df, self.impulse_bars, self.ob_touch_max, self.min_bars_apart)
