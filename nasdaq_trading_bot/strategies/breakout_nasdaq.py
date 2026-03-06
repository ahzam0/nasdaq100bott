"""
3. Breakout Trading — Best for Momentum Traders (NASDAQ).
   Mark key weekly/daily highs and lows; wait for clean close above resistance or below support.
   Enter on retest of the broken level. Target next significant structure level.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy


class BreakoutNasdaqStrategy(BaseStrategy):
    """Key level break (clean close beyond level) then retest for entry."""

    def __init__(
        self,
        structure_lookback: int = 20,
        retest_bars: int = 5,
        close_beyond_pct: float = 0.05,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.structure_lookback = structure_lookback
        self.retest_bars = retest_bars
        self.close_beyond_pct = close_beyond_pct

    def generate_signals(self, df: pd.DataFrame, symbol: str) -> pd.Series:
        if df is None or len(df) < self.structure_lookback + self.retest_bars + 2:
            return pd.Series(0, index=df.index if df is not None else [])

        df = df.copy()
        if "open" not in df.columns:
            df["open"] = df["close"].shift(1).fillna(df["close"])

        idx = df.index
        out = pd.Series(0, index=idx, dtype=int)
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        open_ = df["open"].values

        for i in range(self.structure_lookback + self.retest_bars, len(df) - 1):
            res = np.nanmax(high[i - self.structure_lookback : i - 1])
            sup = np.nanmin(low[i - self.structure_lookback : i - 1])
            if np.isnan(res) or np.isnan(sup):
                continue
            thresh = max(self.close_beyond_pct / 100.0 * (res - sup), 0.01)

            for b in range(1, self.retest_bars + 1):
                j = i - b
                if j < 0:
                    break
                if close[j] > res + thresh:
                    if low[i] <= res + thresh and close[i] > open_[i]:
                        out.iloc[i] = 1
                    break
                if close[j] < sup - thresh:
                    if high[i] >= sup - thresh and close[i] < open_[i]:
                        out.iloc[i] = -1
                    break

        return out
