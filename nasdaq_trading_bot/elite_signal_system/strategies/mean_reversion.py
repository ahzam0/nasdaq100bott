"""
Round 3: Mean reversion (Bollinger Bands + RSI).
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd


class MeanReversionStrategy:
    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        atr_sl_mult: float = 1.5,
        rr_ratio: float = 2.0,
        min_bars_apart: int = 2,
    ):
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_sl_mult = atr_sl_mult
        self.rr_ratio = rr_ratio
        self.min_bars_apart = min_bars_apart

    def generate_entries(self, df: pd.DataFrame, asset: str = "") -> List[Tuple[int, str, float, float, float]]:
        if df is None or len(df) < self.bb_period + 20:
            return []
        df = df.copy()
        mid = df["close"].rolling(self.bb_period).mean()
        std = df["close"].rolling(self.bb_period).std()
        df["bb_upper"] = mid + self.bb_std * std
        df["bb_lower"] = mid - self.bb_std * std
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0).ewm(span=self.rsi_period, adjust=False).mean()
        loss = (-delta).where(delta < 0, 0.0).ewm(span=self.rsi_period, adjust=False).mean()
        df["rsi"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
        df["atr"] = (df["high"] - df["low"]).rolling(14).mean().bfill()
        entries = []
        last_entry_bar = -100
        for i in range(self.bb_period + 15, len(df) - 1):
            if i - last_entry_bar < self.min_bars_apart:
                continue
            atr = df["atr"].iloc[i]
            if pd.isna(atr) or atr <= 0:
                continue
            close = float(df["close"].iloc[i])
            rsi = df["rsi"].iloc[i]
            lower = df["bb_lower"].iloc[i]
            upper = df["bb_upper"].iloc[i]
            if pd.isna(rsi):
                continue
            sl_dist = self.atr_sl_mult * atr
            if close <= lower and rsi < self.rsi_oversold:
                entry = close
                sl = entry - sl_dist
                tp = entry + sl_dist * self.rr_ratio
                entries.append((i, "BUY", entry, sl, tp))
                last_entry_bar = i
            elif close >= upper and rsi > self.rsi_overbought:
                entry = close
                sl = entry + sl_dist
                tp = entry - sl_dist * self.rr_ratio
                entries.append((i, "SELL", entry, sl, tp))
                last_entry_bar = i
        return entries
