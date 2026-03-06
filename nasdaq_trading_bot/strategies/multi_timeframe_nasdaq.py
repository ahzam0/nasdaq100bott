"""
4. Multi-Timeframe Intraday Strategy — Best All-Around (NASDAQ).
   HTF (Daily/4H): define bias (bullish/bearish). MTF (1H): key structure. LTF (15/5min): entry trigger.
   Stops at previous highs (shorts) or lows (longs); targets at previous daily/weekly highs or lows.
   Risk 1%, aim for 3:1 reward-to-risk minimum.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy
from strategies.risk_rules import MIN_REWARD_RISK_RATIO


class MultiTimeframeNasdaqStrategy(BaseStrategy):
    """
    Single-series approximation: use long EMA for HTF bias, medium for structure, short for entry.
    Works on daily or intraday; for true MTF pass higher-timeframe bias externally if needed.
    """

    def __init__(
        self,
        htf_ema: int = 50,
        mtf_ema: int = 21,
        ltf_ema: int = 9,
        atr_period: int = 14,
        min_rr: float = MIN_REWARD_RISK_RATIO,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.htf_ema = htf_ema
        self.mtf_ema = mtf_ema
        self.ltf_ema = ltf_ema
        self.atr_period = atr_period
        self.min_rr = min_rr

    def generate_signals(self, df: pd.DataFrame, symbol: str) -> pd.Series:
        if df is None or len(df) < self.htf_ema + self.atr_period + 5:
            return pd.Series(0, index=df.index if df is not None else [])

        df = df.copy()
        idx = df.index
        df["ema_htf"] = df["close"].ewm(span=self.htf_ema, adjust=False).mean()
        df["ema_mtf"] = df["close"].ewm(span=self.mtf_ema, adjust=False).mean()
        df["ema_ltf"] = df["close"].ewm(span=self.ltf_ema, adjust=False).mean()
        df["atr"] = (df["high"] - df["low"]).rolling(self.atr_period).mean()

        out = pd.Series(0, index=idx, dtype=int)
        close = df["close"].values
        ema_htf = df["ema_htf"].values
        ema_mtf = df["ema_mtf"].values
        ema_ltf = df["ema_ltf"].values
        atr = df["atr"].values
        high = df["high"].values
        low = df["low"].values

        for i in range(self.htf_ema + 2, len(df) - 1):
            if np.isnan(ema_htf[i]) or np.isnan(atr[i]) or atr[i] <= 0:
                continue
            bias_bull = close[i] > ema_htf[i]
            bias_bear = close[i] < ema_htf[i]
            # Structure: price on right side of MTF
            structure_bull = close[i] > ema_mtf[i]
            structure_bear = close[i] < ema_mtf[i]
            # LTF pullback to EMA then resume
            pullback_long = ema_ltf[i - 1] >= close[i - 1] and close[i] > ema_ltf[i]
            pullback_short = ema_ltf[i - 1] <= close[i - 1] and close[i] < ema_ltf[i]

            if bias_bull and structure_bull and pullback_long:
                out.iloc[i] = 1
            elif bias_bear and structure_bear and pullback_short:
                out.iloc[i] = -1

        return out
