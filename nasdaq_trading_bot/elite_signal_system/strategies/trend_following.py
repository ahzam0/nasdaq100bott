"""
Round 1: Trend-following with momentum filters (EMA crossovers + RSI + volume).
Returns list of (bar_index, direction, entry_price, sl, tp).
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd


class TrendFollowingStrategy:
    def __init__(
        self,
        ema_fast: int = 9,
        ema_slow: int = 21,
        rsi_period: int = 14,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        atr_sl_mult: float = 2.0,
        rr_ratio: float = 2.0,
        min_bars_apart: int = 3,
    ):
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.rsi_period = rsi_period
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.atr_sl_mult = atr_sl_mult
        self.rr_ratio = rr_ratio
        self.min_bars_apart = min_bars_apart

    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["ema_f"] = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
        df["ema_s"] = df["close"].ewm(span=self.ema_slow, adjust=False).mean()
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0).ewm(span=self.rsi_period, adjust=False).mean()
        loss = (-delta).where(delta < 0, 0.0).ewm(span=self.rsi_period, adjust=False).mean()
        rs = gain / loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        df["atr"] = (df["high"] - df["low"]).rolling(14).mean().bfill()
        if "volume" in df.columns:
            df["vol_ma"] = df["volume"].rolling(20).mean().shift(1)
        return df

    def generate_entries(self, df: pd.DataFrame, asset: str = "") -> List[Tuple[int, str, float, float, float]]:
        if df is None or len(df) < 50:
            return []
        df = self._add_indicators(df)
        entries = []
        last_entry_bar = -100
        for i in range(self.ema_slow + 1, len(df) - 1):
            if i - last_entry_bar < self.min_bars_apart:
                continue
            atr = df["atr"].iloc[i]
            if pd.isna(atr) or atr <= 0:
                continue
            close = df["close"].iloc[i]
            ema_f = df["ema_f"].iloc[i]
            ema_s = df["ema_s"].iloc[i]
            rsi = df["rsi"].iloc[i]
            if pd.isna(rsi):
                continue
            vol_ok = True
            if "vol_ma" in df.columns and not pd.isna(df["vol_ma"].iloc[i]):
                vol_ok = df["volume"].iloc[i] >= df["vol_ma"].iloc[i] * 0.8
            sl_dist = self.atr_sl_mult * atr
            if ema_f > ema_s and df["ema_f"].iloc[i - 1] <= df["ema_s"].iloc[i - 1] and rsi < self.rsi_overbought and vol_ok:
                entry = float(close)
                sl = entry - sl_dist
                tp = entry + sl_dist * self.rr_ratio
                entries.append((i, "BUY", entry, sl, tp))
                last_entry_bar = i
            elif ema_f < ema_s and df["ema_f"].iloc[i - 1] >= df["ema_s"].iloc[i - 1] and rsi > self.rsi_oversold and vol_ok:
                entry = float(close)
                sl = entry + sl_dist
                tp = entry - sl_dist * self.rr_ratio
                entries.append((i, "SELL", entry, sl, tp))
                last_entry_bar = i
        return entries
