"""
Round 2: Breakout (support/resistance + ATR-based breakouts).
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd


class BreakoutStrategy:
    def __init__(
        self,
        lookback: int = 20,
        atr_mult: float = 1.5,
        rr_ratio: float = 2.0,
        min_bars_apart: int = 5,
    ):
        self.lookback = lookback
        self.atr_mult = atr_mult
        self.rr_ratio = rr_ratio
        self.min_bars_apart = min_bars_apart

    def generate_entries(self, df: pd.DataFrame, asset: str = "") -> List[Tuple[int, str, float, float, float]]:
        if df is None or len(df) < self.lookback + 10:
            return []
        df = df.copy()
        df["atr"] = (df["high"] - df["low"]).rolling(14).mean().bfill()
        df["resistance"] = df["high"].rolling(self.lookback).max().shift(1)
        df["support"] = df["low"].rolling(self.lookback).min().shift(1)
        entries = []
        last_entry_bar = -100
        for i in range(self.lookback + 5, len(df) - 1):
            if i - last_entry_bar < self.min_bars_apart:
                continue
            atr = df["atr"].iloc[i]
            if pd.isna(atr) or atr <= 0:
                continue
            close = float(df["close"].iloc[i])
            res = df["resistance"].iloc[i]
            sup = df["support"].iloc[i]
            if pd.isna(res) or pd.isna(sup):
                continue
            sl_dist = self.atr_mult * atr
            if close >= res * 0.998:
                entry = close
                sl = entry - sl_dist
                tp = entry + sl_dist * self.rr_ratio
                entries.append((i, "BUY", entry, sl, tp))
                last_entry_bar = i
            elif close <= sup * 1.002:
                entry = close
                sl = entry + sl_dist
                tp = entry - sl_dist * self.rr_ratio
                entries.append((i, "SELL", entry, sl, tp))
                last_entry_bar = i
        return entries
