"""
2. Smart Money Concepts (SMC) — Best for Day Traders (NASDAQ).
   Identify liquidity pools (equal highs/lows); wait for sweep then reverse.
   Enter on displacement candle. Best during NY Kill Zone 9:30–11:00 AM EST.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from strategies.best_times import in_kill_zone


class SmartMoneyNasdaqStrategy(BaseStrategy):
    """Liquidity sweep (break of equal highs/lows) then reversal; displacement candle entry."""

    def __init__(
        self,
        lookback_bars: int = 20,
        equal_level_tolerance_pct: float = 0.1,
        displacement_body_pct: float = 0.5,
        prefer_kill_zone: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.lookback_bars = lookback_bars
        self.equal_level_tolerance_pct = equal_level_tolerance_pct
        self.displacement_body_pct = displacement_body_pct
        self.prefer_kill_zone = prefer_kill_zone

    def _rolling_high_low(self, df: pd.DataFrame) -> tuple:
        high = df["high"].values
        low = df["low"].values
        n = len(df)
        recent_high = np.full(n, np.nan)
        recent_low = np.full(n, np.nan)
        for i in range(self.lookback_bars, n):
            recent_high[i] = np.nanmax(high[i - self.lookback_bars : i])
            recent_low[i] = np.nanmin(low[i - self.lookback_bars : i])
        return recent_high, recent_low

    def generate_signals(self, df: pd.DataFrame, symbol: str) -> pd.Series:
        if df is None or len(df) < self.lookback_bars + 5:
            return pd.Series(0, index=df.index if df is not None else [])

        idx = df.index
        out = pd.Series(0, index=idx, dtype=int)
        high, low = df["high"].values, df["low"].values
        open_, close = df["open"].values, df["close"].values
        recent_high, recent_low = self._rolling_high_low(df)
        tol = self.equal_level_tolerance_pct / 100.0

        for i in range(self.lookback_bars + 2, len(df) - 1):
            if self.prefer_kill_zone and not in_kill_zone(idx[i]):
                continue
            rh, rl = recent_high[i - 1], recent_low[i - 1]
            if np.isnan(rh) or np.isnan(rl):
                continue
            # Sweep high: price took out recent high then closed back below (liquidity grab)
            sweep_high = high[i] >= rh * (1 - tol) and close[i] < open_[i] and close[i] < rh * (1 - tol * 0.5)
            # Displacement: strong opposite candle (big body)
            body = abs(close[i] - open_[i])
            range_ = high[i] - low[i]
            displacement_down = range_ > 0 and body / range_ >= self.displacement_body_pct and close[i] < open_[i]
            if sweep_high and displacement_down:
                out.iloc[i + 1] = -1
                continue
            # Sweep low: price took out recent low then closed back above
            sweep_low = low[i] <= rl * (1 + tol) and close[i] > open_[i] and close[i] > rl * (1 + tol * 0.5)
            displacement_up = range_ > 0 and body / range_ >= self.displacement_body_pct and close[i] > open_[i]
            if sweep_low and displacement_up:
                out.iloc[i + 1] = 1

        return out
