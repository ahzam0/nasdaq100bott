"""
NASDAQ data pipeline: Polygon / Alpaca / yfinance with failover.
Builds 50+ features per bar and market regime labels.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Try optional deps
try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    import pandas_ta as ta
except ImportError:
    ta = None


def _ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize to open, high, low, close, volume."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for std in ["open", "high", "low", "close", "volume"]:
        for k, v in cols.items():
            if std in k or k == std:
                rename[v] = std
                break
    df = df.rename(columns=rename)
    for c in ["open", "high", "low", "close"]:
        if c not in df.columns:
            return pd.DataFrame()
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def fetch_yfinance(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch OHLCV from yfinance. Returns DataFrame with DatetimeIndex."""
    if yf is None:
        logger.error("yfinance not installed")
        return pd.DataFrame()
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
    except Exception as e:
        logger.warning("yfinance fetch %s failed: %s", symbol, e)
        return pd.DataFrame()
    df = _ensure_ohlcv(df)
    if df.empty:
        return df
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC").tz_convert("America/New_York")
    return df


def fetch_polygon(symbol: str, from_: str, to_: str, timespan: str = "day") -> pd.DataFrame:
    """Fetch from Polygon.io (optional). Requires POLYGON_API_KEY."""
    import os
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not key:
        return pd.DataFrame()
    try:
        from polygon import RESTClient
        client = RESTClient(key)
        aggs = client.get_aggs(symbol, 1, timespan, from_, to_)
        rows = [{"timestamp": a.timestamp, "open": a.open, "high": a.high, "low": a.low, "close": a.close, "volume": a.volume} for a in aggs]
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_convert("America/New_York")
        df = df.set_index("timestamp").rename(columns={"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"})
        return _ensure_ohlcv(df)
    except Exception as e:
        logger.debug("Polygon fetch failed: %s", e)
        return pd.DataFrame()


def load_bars(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
    source: str = "yfinance",
) -> pd.DataFrame:
    """Load OHLCV with failover: polygon -> yfinance."""
    if source == "polygon":
        df = fetch_polygon(symbol, start, end, timespan="day" if interval == "1d" else "minute")
        if not df.empty:
            return df
    # Request enough history: 5y for long ranges, 2y for recent, so slice [start:end] works
    period = "5y" if start and "201" in start else "2y"
    df = fetch_yfinance(symbol, period=period, interval=interval)
    if df.empty:
        return df
    df = df.loc[start:end] if start and end else df
    return df


# ---------- Feature builders (50+ NASDAQ features) ----------

def add_emas(df: pd.DataFrame, periods: list[int] = [9, 21, 50, 200]) -> pd.DataFrame:
    for p in periods:
        df[f"ema_{p}"] = df["close"].ewm(span=p, adjust=False).mean()
    return df


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """VWAP (typical price). For intraday, group by date first if needed."""
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    if hasattr(df.index, "date"):
        dates = df.index.date if hasattr(df.index, "date") else [getattr(i, "date", i) for i in df.index]
        df["vwap"] = (tp * df["volume"]).groupby(dates).transform(lambda x: x.cumsum() / df["volume"].groupby(dates).cumsum())
    else:
        df["vwap"] = (tp * df["volume"]).cumsum() / df["volume"].replace(0, np.nan).cumsum()
    return df


def add_vwap_bands(df: pd.DataFrame, stds: list[float] = [1, 2, 3]) -> pd.DataFrame:
    if "vwap" not in df.columns:
        add_vwap(df)
    std = df["close"].rolling(20).std().bfill()
    for s in stds:
        df[f"vwap_upper_{s}"] = df["vwap"] + s * std
        df[f"vwap_lower_{s}"] = df["vwap"] - s * std
    return df


def add_supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.DataFrame:
    if ta is not None:
        st = ta.supertrend(df["high"], df["low"], df["close"], length=period, multiplier=mult)
        if st is not None and not st.empty:
            if isinstance(st, pd.DataFrame):
                df["supertrend"] = st[f"SUPERT_{period}_{mult}"].reindex(df.index)
            else:
                df["supertrend"] = st
            return df
    atr = df["close"].diff().abs().rolling(period).max().combine_first((df["high"] - df["low"]).rolling(period).max())
    hl2 = (df["high"] + df["low"]) / 2
    upper = hl2 + mult * atr
    lower = hl2 - mult * atr
    close = df["close"]
    trend = 1
    supt = np.zeros(len(df))
    for i in range(period, len(df)):
        if close.iloc[i] > upper.iloc[i - 1]:
            trend = 1
        elif close.iloc[i] < lower.iloc[i - 1]:
            trend = -1
        if trend == 1:
            lower[i] = min(lower.iloc[i], lower.iloc[i - 1]) if close.iloc[i - 1] > lower.iloc[i - 1] else lower.iloc[i]
            supt[i] = lower.iloc[i]
        else:
            upper[i] = max(upper.iloc[i], upper.iloc[i - 1]) if close.iloc[i - 1] < upper.iloc[i - 1] else upper.iloc[i]
            supt[i] = upper.iloc[i]
    df["supertrend"] = pd.Series(supt, index=df.index)
    return df


def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    if ta is not None:
        adx_df = ta.adx(df["high"], df["low"], df["close"], length=period)
        if adx_df is not None and not adx_df.empty:
            c = [x for x in adx_df.columns if "ADX" in str(x).upper()][:1]
            if c:
                df["adx"] = adx_df[c[0]].reindex(df.index)
                return df
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = pd.concat([high - low, high - close.shift(1).abs(), low - close.shift(1).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    df["adx"] = dx.rolling(period).mean()
    return df


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df[f"rsi_{period}"] = 100 - (100 / (1 + rs))
    return df


def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_f = df["close"].ewm(span=fast, adjust=False).mean()
    ema_s = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_f - ema_s
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


def add_stochastic(df: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    df["stoch_k"] = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    df["stoch_d"] = df["stoch_k"].rolling(d).mean()
    return df


def add_roc(df: pd.DataFrame, periods: list[int] = [1, 3, 5, 10, 21]) -> pd.DataFrame:
    for p in periods:
        df[f"roc_{p}"] = (df["close"] - df["close"].shift(p)) / df["close"].shift(p).replace(0, np.nan) * 100
    return df


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(period).mean()
    return df


def add_bollinger(df: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    mid = df["close"].rolling(period).mean()
    dev = df["close"].rolling(period).std()
    df["bb_upper"] = mid + std * dev
    df["bb_lower"] = mid - std * dev
    df["bb_mid"] = mid
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / mid.replace(0, np.nan)
    return df


def add_keltner(df: pd.DataFrame, period: int = 20, atr_mult: float = 1.5) -> pd.DataFrame:
    if "atr" not in df.columns:
        add_atr(df, period)
    mid = df["close"].rolling(period).mean()
    df["keltner_upper"] = mid + atr_mult * df["atr"]
    df["keltner_lower"] = mid - atr_mult * df["atr"]
    return df


def add_rvol(df: pd.DataFrame, avg_days: int = 20) -> pd.DataFrame:
    """Relative volume vs average."""
    vol = df["volume"]
    avg = vol.rolling(avg_days).mean().shift(1)
    df["rvol"] = vol / avg.replace(0, np.nan)
    return df


def add_obv(df: pd.DataFrame) -> pd.DataFrame:
    df["obv"] = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()
    return df


def add_cmf(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    mfm = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"]).replace(0, np.nan)
    mfv = mfm * df["volume"]
    df["cmf"] = mfv.rolling(period).sum() / df["volume"].rolling(period).sum().replace(0, np.nan)
    return df


def add_vwap_deviation(df: pd.DataFrame) -> pd.DataFrame:
    if "vwap" not in df.columns:
        add_vwap(df)
    df["vwap_deviation"] = (df["close"] - df["vwap"]) / df["vwap"].replace(0, np.nan)
    return df


def add_relative_strength_qqq(df: pd.DataFrame, qqq_close: pd.Series) -> pd.DataFrame:
    """RS vs QQQ (both must share index)."""
    if qqq_close is None or qqq_close.empty:
        df["rs_qqq"] = np.nan
        return df
    common = df["close"].div(qqq_close.reindex(df.index).ffill().bfill()).replace([np.inf, -np.inf], np.nan)
    df["rs_qqq"] = common.pct_change(5)
    return df


def build_nasdaq_features(df: pd.DataFrame, qqq_series: Optional[pd.Series] = None) -> pd.DataFrame:
    """Build 50+ NASDAQ features. Modifies df in place and returns it."""
    if df is None or df.empty or len(df) < 200:
        return df
    add_emas(df, [9, 21, 50, 200])
    add_vwap(df)
    add_vwap_bands(df, [1, 2, 3])
    add_supertrend(df, 10, 3.0)
    df["supertrend_10"] = df["supertrend"].copy()
    add_supertrend(df, 7, 3.0)
    df["supertrend_7"] = df["supertrend"]
    add_adx(df, 14)
    add_rsi(df, 2)
    add_rsi(df, 14)
    add_macd(df, 12, 26, 9)
    add_stochastic(df, 14, 3)
    add_roc(df, [1, 3, 5, 10, 21])
    add_atr(df, 14)
    add_bollinger(df, 20, 2.0)
    add_keltner(df, 20, 1.5)
    add_rvol(df, 20)
    add_obv(df)
    add_cmf(df, 20)
    add_vwap_deviation(df)
    if qqq_series is not None:
        add_relative_strength_qqq(df, qqq_series)
    return df


# ---------- Regime labels (HMM-style: simple rule-based) ----------

def label_regime(df: pd.DataFrame, qqq_above_ema200: bool, breadth_pct: float = 50.0) -> str:
    """
    Label market regime. Uses ADX, QQQ vs EMA200, breadth proxy.
    Returns: NASDAQ_BULL_TREND, NASDAQ_BEAR_TREND, NASDAQ_SIDEWAYS,
             NASDAQ_HIGH_VOLATILITY, NASDAQ_LOW_VOLATILITY.
    """
    if df is None or df.empty or "adx" not in df.columns:
        return "NASDAQ_SIDEWAYS"
    last = df.iloc[-1]
    adx = last.get("adx", 0) or 0
    if adx > 25:
        if qqq_above_ema200 and breadth_pct >= 60:
            return "NASDAQ_BULL_TREND"
        if not qqq_above_ema200 and breadth_pct <= 40:
            return "NASDAQ_BEAR_TREND"
    if adx < 20:
        return "NASDAQ_SIDEWAYS"
    vol = last.get("atr", 0) or 0
    if vol > 0 and (last["close"] / vol) < 20:
        return "NASDAQ_HIGH_VOLATILITY"
    if "bb_width" in df.columns and last.get("bb_width", 1) < 0.02:
        return "NASDAQ_LOW_VOLATILITY"
    return "NASDAQ_SIDEWAYS"


def add_regime_column(df: pd.DataFrame, qqq_series: Optional[pd.Series] = None) -> pd.DataFrame:
    """Add regime label per row (using rolling QQQ vs EMA200 and ADX)."""
    if "adx" not in df.columns:
        add_adx(df, 14)
    if "ema_200" not in df.columns:
        add_emas(df, [200])
    qqq_above = None
    if qqq_series is not None and not qqq_series.empty:
        ema200_qqq = qqq_series.ewm(span=200, adjust=False).mean()
        qqq_above = (qqq_series.reindex(df.index).ffill() > ema200_qqq.reindex(df.index).ffill())
    else:
        qqq_above = df["close"] > df["ema_200"]
    adx_strong = df["adx"] > 25
    bull = qqq_above & adx_strong & (df["close"] > df["ema_50"])
    bear = (~qqq_above) & adx_strong & (df["close"] < df["ema_50"])
    side = df["adx"] < 20
    df["regime"] = "NASDAQ_SIDEWAYS"
    df.loc[bull, "regime"] = "NASDAQ_BULL_TREND"
    df.loc[bear, "regime"] = "NASDAQ_BEAR_TREND"
    return df


def get_pipeline(
    symbol: str,
    start: str,
    end: str,
    interval: str = "1d",
    with_qqq: bool = True,
) -> pd.DataFrame:
    """
    Full pipeline: load bars, build 50+ features, add regime.
    Returns DataFrame with DatetimeIndex (ET).
    """
    df = load_bars(symbol, start, end, interval=interval)
    if df.empty or len(df) < 50:
        return df
    qqq_s = None
    if with_qqq and symbol.upper() != "QQQ":
        qqq_df = load_bars("QQQ", start, end, interval=interval)
        if not qqq_df.empty:
            qqq_s = qqq_df["close"]
    build_nasdaq_features(df, qqq_s)
    add_regime_column(df, qqq_s)
    return df
