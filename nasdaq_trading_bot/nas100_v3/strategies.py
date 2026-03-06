"""
NAS100 v3.0 — Strategy A (EMA Pullback), B (ORB), C (PDH/PDL).
Simple mechanical rules only. Each returns (bar_i, strategy, direction, entry, sl, tp1, tp2, trail_pts, risk_pct).
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from nas100_v3.config import (
    EMA_TREND_SEPARATION_PTS,
    SL_BEYOND_PULLBACK_WICK_PTS,
    TP1_RR,
    TP2_RR,
    TP3_TRAIL_PTS,
    ORB_SL_BUFFER_PTS,
    ORB_RANGE_MAX_PTS,
    ORB_RANGE_MIN_PTS,
    PDH_PDL_SL_PTS,
    PDH_PDL_TP1_PTS,
    PDH_PDL_TP2_PTS,
    PDH_PDL_TRAIL_PTS,
    PDH_PDL_SKIP_MOVE_PTS,
    RISK_TABLE,
)


def _ema(series: pd.Series, period: int) -> np.ndarray:
    return series.ewm(span=period, adjust=False).mean().values


def strategy_a_ema_pullback(df: pd.DataFrame) -> List[Tuple[int, str, str, float, float, float, float, float, float]]:
    """
    Only 3 conditions: (1) H1 trend EMA20 vs EMA50, (2) price touches EMA20, (3) trigger candle closes in trend.
    Daily proxy: trend = EMA20 vs EMA50. Touch = low <= EMA20 (BUY) or high >= EMA20 (SELL). Trigger = same bar close.
    """
    if df is None or len(df) < 55:
        return []
    entries = []
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    open_ = df["open"].values
    ema20 = _ema(df["close"], 20)
    ema50 = _ema(df["close"], 50)
    for i in range(20, len(df) - 1):
        if np.isnan(ema20[i]) or np.isnan(ema50[i]):
            continue
        sep = abs(ema20[i] - ema50[i])
        if sep < EMA_TREND_SEPARATION_PTS:
            continue
        # Uptrend: EMA20 > EMA50 → BUY only
        if ema20[i] > ema50[i]:
            if low[i] <= ema20[i] + 2 and close[i] > open_[i]:  # touch + bullish close
                sl = low[i] - SL_BEYOND_PULLBACK_WICK_PTS
                if sl >= close[i]:
                    continue
                sl_pts = close[i] - sl
                entries.append((i, "EMA_Pullback", "BUY", float(close[i]), sl,
                                close[i] + sl_pts * TP1_RR, close[i] + sl_pts * TP2_RR, TP3_TRAIL_PTS, 0.015))
        else:
            if high[i] >= ema20[i] - 2 and close[i] < open_[i]:  # touch + bearish close
                sl = high[i] + SL_BEYOND_PULLBACK_WICK_PTS
                if sl <= close[i]:
                    continue
                sl_pts = sl - close[i]
                entries.append((i, "EMA_Pullback", "SELL", float(close[i]), sl,
                                close[i] - sl_pts * TP1_RR, close[i] - sl_pts * TP2_RR, TP3_TRAIL_PTS, 0.015))
    return entries


def strategy_b_orb(df: pd.DataFrame) -> List[Tuple[int, str, str, float, float, float, float, float, float]]:
    """
    Opening range = prev bar high/low. Breakout = close above OR high (BUY) or below OR low (SELL).
    Skip if range > 100 or < 15 pts.
    """
    if df is None or len(df) < 3:
        return []
    entries = []
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    for i in range(2, len(df) - 1):
        or_high = high[i - 1]
        or_low = low[i - 1]
        range_pts = or_high - or_low
        if range_pts > ORB_RANGE_MAX_PTS or range_pts < ORB_RANGE_MIN_PTS:
            continue
        if close[i] > or_high:
            sl = or_low - ORB_SL_BUFFER_PTS
            entries.append((i, "ORB", "BUY", float(close[i]), sl,
                            close[i] + range_pts, close[i] + range_pts * 2, 25.0, 0.015))
        elif close[i] < or_low:
            sl = or_high + ORB_SL_BUFFER_PTS
            entries.append((i, "ORB", "SELL", float(close[i]), sl,
                            close[i] - range_pts, close[i] - range_pts * 2, 25.0, 0.015))
    return entries


def strategy_c_pdh_pdl(df: pd.DataFrame) -> List[Tuple[int, str, str, float, float, float, float, float, float]]:
    """
    PDH/PDL = prev day high/low. Break and close above PDH → BUY, below PDL → SELL.
    Skip if price already moved >150 pts from prev close. TP1=40, TP2=80, trail 30.
    """
    if df is None or len(df) < 3:
        return []
    entries = []
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    for i in range(2, len(df) - 1):
        pdh = high[i - 1]
        pdl = low[i - 1]
        prev_close = close[i - 2]
        if abs(close[i] - prev_close) > PDH_PDL_SKIP_MOVE_PTS:
            continue
        if close[i] > pdh:
            sl = pdh - PDH_PDL_SL_PTS
            entries.append((i, "PDH_PDL", "BUY", float(close[i]), sl,
                            close[i] + PDH_PDL_TP1_PTS, close[i] + PDH_PDL_TP2_PTS, PDH_PDL_TRAIL_PTS, 0.01))
        elif close[i] < pdl:
            sl = pdl + PDH_PDL_SL_PTS
            entries.append((i, "PDH_PDL", "SELL", float(close[i]), sl,
                            close[i] - PDH_PDL_TP1_PTS, close[i] - PDH_PDL_TP2_PTS, PDH_PDL_TRAIL_PTS, 0.01))
    return entries


def combine_and_cap_per_day(
    list_a: List,
    list_b: List,
    list_c: List,
    df: pd.DataFrame,
    max_per_day: int = 3,
) -> List[Tuple[int, str, str, float, float, float, float, float, float]]:
    """
    Combine all signals, sort by bar. Cap at max_per_day per day; assign risk 1.5%, 1%, 0.5%.
    """
    combined = []
    for e in list_a + list_b + list_c:
        combined.append(e)
    combined.sort(key=lambda x: x[0])
    if not combined:
        return []
    out = []
    day_count = {}
    risk_tiers = [RISK_TABLE["first_trade_pct"] / 100.0, RISK_TABLE["second_trade_pct"] / 100.0, RISK_TABLE["third_trade_pct"] / 100.0]
    for e in combined:
        bar_i, strat, direction, entry, sl, tp1, tp2, trail, _ = e
        try:
            d = df.index[bar_i].date()
        except Exception:
            d = bar_i
        n = day_count.get(d, 0)
        if n >= max_per_day:
            continue
        risk = risk_tiers[min(n, 2)]
        out.append((bar_i, strat, direction, entry, sl, tp1, tp2, trail, risk))
        day_count[d] = n + 1
    return out


def generate_all_signals(df: pd.DataFrame) -> List[Tuple[int, str, str, float, float, float, float, float, float]]:
    """Run A, B, C and combine with max 3 per day and risk tiers."""
    a = strategy_a_ema_pullback(df)
    b = strategy_b_orb(df)
    c = strategy_c_pdh_pdl(df)
    return combine_and_cap_per_day(a, b, c, df, max_per_day=RISK_TABLE["max_trades_per_day"])
