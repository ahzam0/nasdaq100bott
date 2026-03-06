"""
5. Momentum/Risk-Adjusted Strategy — Best for Investors (NASDAQ).
   Risk-adjusted momentum: select top-performing NASDAQ names with variable allocation to
   treasuries or gold to smooth the equity curve and provide crash protection in bear markets.
   (Single-asset version: momentum filter only; full allocation logic is portfolio-level.)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy


class MomentumRiskAdjustedNasdaqStrategy(BaseStrategy):
    """
    Momentum filter for NASDAQ: only long when price is above medium-term EMA and momentum positive.
    No short; flat when trend weak (risk-off). Use with portfolio allocation to treasuries/gold elsewhere.
    """

    def __init__(
        self,
        trend_ema: int = 50,
        momentum_period: int = 20,
        min_momentum_pct: float = 0.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.trend_ema = trend_ema
        self.momentum_period = momentum_period
        self.min_momentum_pct = min_momentum_pct

    def generate_signals(self, df: pd.DataFrame, symbol: str) -> pd.Series:
        if df is None or len(df) < self.trend_ema + self.momentum_period:
            return pd.Series(0, index=df.index if df is not None else [])

        df = df.copy()
        idx = df.index
        df["ema"] = df["close"].ewm(span=self.trend_ema, adjust=False).mean()
        df["momentum"] = df["close"].pct_change(self.momentum_period) * 100.0

        out = pd.Series(0, index=idx, dtype=int)
        close = df["close"].values
        ema = df["ema"].values
        mom = df["momentum"].values

        for i in range(self.trend_ema + self.momentum_period, len(df)):
            if np.isnan(ema[i]) or np.isnan(mom[i]):
                continue
            above_trend = close[i] > ema[i]
            momentum_ok = mom[i] >= self.min_momentum_pct
            if above_trend and momentum_ok:
                out.iloc[i] = 1
            # No short in this investor-style strategy

        return out
