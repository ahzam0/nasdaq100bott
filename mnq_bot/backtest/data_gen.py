"""
Generate synthetic 1m and 15m MNQ data for backtesting.
Produces multi-day session data (7:00–11:00 EST) with structure for setups.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

EST = ZoneInfo("America/New_York")

# Session: 7:00–11:00 EST = 4 hours = 240 minutes
SESSION_START_HOUR, SESSION_START_MIN = 7, 0
SESSION_END_HOUR, SESSION_END_MIN = 11, 0
MINUTES_PER_SESSION = (SESSION_END_HOUR - SESSION_START_HOUR) * 60 + (SESSION_END_MIN - SESSION_START_MIN)


def generate_mnq_session(start_date: datetime, seed: int, base_price: float = 19000.0) -> pd.DataFrame:
    """One session (7:00–11:00 EST) of 1m bars. start_date is EST date."""
    rng = np.random.default_rng(seed)
    n = MINUTES_PER_SESSION
    dt = start_date.replace(hour=SESSION_START_HOUR, minute=0, second=0, microsecond=0, tzinfo=EST)
    index = pd.date_range(dt, periods=n, freq="1min", tz=EST)
    # Random walk with slight mean reversion and trend bursts
    returns = rng.standard_normal(n) * 1.5
    trend = np.sin(np.linspace(0, 2 * np.pi, n)) * 0.3 + rng.standard_normal(n) * 0.2
    close = base_price + np.cumsum(returns + trend)
    high = close + np.abs(rng.standard_normal(n) * 2)
    low = close - np.abs(rng.standard_normal(n) * 2)
    open_ = np.roll(close, 1)
    open_[0] = base_price
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": rng.integers(500, 5000, n)}, index=index)
    df.index.name = "timestamp"
    return df


def generate_multi_day_1m(trading_days: int, start_price: float = 19000.0, seed: int = 42) -> pd.DataFrame:
    """Multiple sessions of 1m data. Each day 7:00–11:00 EST (weekdays only)."""
    frames = []
    price = start_price
    start = datetime(2024, 1, 2, tzinfo=EST)  # First trading day
    collected = 0
    d = 0
    while collected < trading_days:
        dt = start + timedelta(days=d)
        if dt.weekday() < 5:  # Mon–Fri
            df = generate_mnq_session(dt, seed=seed + collected * 100, base_price=price)
            frames.append(df)
            price = float(df["close"].iloc[-1])
            collected += 1
        d += 1
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, axis=0)


def resample_15m(df_1m: pd.DataFrame) -> pd.DataFrame:
    """Resample 1m to 15m OHLCV."""
    if df_1m.empty:
        return pd.DataFrame()
    return df_1m.resample("15min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna(how="all")


def generate_backtest_data(trading_days: int = 30, start_price: float = 19000.0, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (df_1m, df_15m) for backtest."""
    df_1m = generate_multi_day_1m(trading_days, start_price=start_price, seed=seed)
    df_15m = resample_15m(df_1m)
    return df_1m, df_15m
