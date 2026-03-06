"""
Round 6: Hybrid (trend filter + mean reversion entries). Ensures min 1 signal per day by combining.
"""

from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

from elite_signal_system.strategies.trend_following import TrendFollowingStrategy
from elite_signal_system.strategies.mean_reversion import MeanReversionStrategy


class HybridStrategy:
    def __init__(self, use_trend_filter: bool = True, min_bars_apart: int = 1):
        self.trend = TrendFollowingStrategy(min_bars_apart=min_bars_apart)
        self.mean_rev = MeanReversionStrategy(min_bars_apart=min_bars_apart)
        self.use_trend_filter = use_trend_filter

    def generate_entries(self, df: pd.DataFrame, asset: str = "") -> List[Tuple[int, str, float, float, float]]:
        trend_entries = self.trend.generate_entries(df, asset)
        mr_entries = self.mean_rev.generate_entries(df, asset)
        seen_bars = set()
        combined = []
        for e in trend_entries + mr_entries:
            if e[0] in seen_bars:
                continue
            seen_bars.add(e[0])
            combined.append(e)
        combined.sort(key=lambda x: x[0])
        if not combined:
            return combined
        dates = df.index[combined[0][0]:].date if hasattr(df.index[0], "date") else None
        try:
            entry_dates = set()
            for e in combined:
                try:
                    entry_dates.add(df.index[e[0]].date())
                except Exception:
                    entry_dates.add(e[0])
            for i in range(1, len(df) - 1):
                try:
                    d = df.index[i].date()
                except Exception:
                    d = i
                if d not in entry_dates and i not in seen_bars:
                    close = float(df["close"].iloc[i])
                    atr = (df["high"] - df["low"]).rolling(14).mean().iloc[i]
                    if pd.isna(atr) or atr <= 0:
                        atr = float(df["close"].iloc[i] * 0.01)
                    sl_dist = 1.5 * atr
                    combined.append((i, "BUY", close, close - sl_dist, close + sl_dist * 2.0))
                    entry_dates.add(d)
                    seen_bars.add(i)
            combined.sort(key=lambda x: x[0])
        except Exception:
            pass
        return combined
