"""
1. Trend Following — Best for Swing & Position Traders (NASDAQ).
   Use 200 EMA on daily to determine macro trend; only long above, short below.
   Confirm with MACD crossovers and RSI above 50. Hold trades for days to weeks.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy


class TrendFollowingNasdaqStrategy(BaseStrategy):
    """200 EMA + MACD crossover + RSI > 50 for longs, RSI < 50 for shorts."""

    def __init__(
        self,
        ema_period: int = 200,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        rsi_period: int = 14,
        rsi_neutral: float = 50.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.ema_period = ema_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.rsi_period = rsi_period
        self.rsi_neutral = rsi_neutral

    def generate_signals(self, df: pd.DataFrame, symbol: str) -> pd.Series:
        if df is None or len(df) < self.ema_period + self.macd_slow:
            return pd.Series(0, index=df.index if df is not None else [])

        df = df.copy()
        idx = df.index

        # 200 EMA (or configurable)
        df["ema"] = df["close"].ewm(span=self.ema_period, adjust=False).mean()
        # MACD
        ema_f = df["close"].ewm(span=self.macd_fast, adjust=False).mean()
        ema_s = df["close"].ewm(span=self.macd_slow, adjust=False).mean()
        df["macd"] = ema_f - ema_s
        df["macd_signal"] = df["macd"].ewm(span=self.macd_signal, adjust=False).mean()
        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(span=self.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(span=self.rsi_period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))

        out = pd.Series(0, index=idx, dtype=int)
        close = df["close"].values
        ema = df["ema"].values
        macd = df["macd"].values
        macd_sig = df["macd_signal"].values
        rsi = df["rsi"].values

        for i in range(1, len(df)):
            if np.isnan(ema[i]) or np.isnan(rsi[i]) or np.isnan(macd[i]):
                continue
            above_ema = close[i] > ema[i]
            below_ema = close[i] < ema[i]
            macd_cross_up = macd[i] > macd_sig[i] and macd[i - 1] <= macd_sig[i - 1]
            macd_cross_dn = macd[i] < macd_sig[i] and macd[i - 1] >= macd_sig[i - 1]
            rsi_above_50 = rsi[i] > self.rsi_neutral
            rsi_below_50 = rsi[i] < self.rsi_neutral

            if above_ema and (macd_cross_up or (macd[i] > macd_sig[i] and rsi_above_50)):
                out.iloc[i] = 1
            elif below_ema and (macd_cross_dn or (macd[i] < macd_sig[i] and rsi_below_50)):
                out.iloc[i] = -1

        return out
