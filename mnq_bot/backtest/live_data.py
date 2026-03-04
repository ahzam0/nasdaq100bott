"""
Fetch live/current market data from free APIs for backtesting.
Uses yfinance (Yahoo Finance) for NQ futures – same price as MNQ, free, no API key.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")
IST = ZoneInfo("Asia/Kolkata")

# IST session 8:00 PM–11:30 PM = 20:00–23:30 (minute_of_day 1200–1410)
IST_SESSION_START_MIN = 20 * 60
IST_SESSION_END_MIN = 23 * 60 + 30

# Yahoo: 1m data = last 7 days only; 15m = up to 60 days
# If NQ=F fails (rate limit/region), we try index then ES futures
YF_SYMBOLS = ("NQ=F", "^NDX", "ES=F", "^IXIC")  # try in order
PERIOD_1M = "7d"     # max for 1m
PERIOD_15M = "7d"    # same window so 1m and 15m align
INTERVAL_1M = "1m"
INTERVAL_15M = "15m"


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure columns open, high, low, close, volume and DatetimeIndex."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    # yfinance: single symbol -> Open, High, Low, Close, Volume; multi -> MultiIndex
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    col_map = {}
    for c in df.columns:
        cstr = str(c).lower()
        if "open" in cstr:
            col_map[c] = "open"
        elif "high" in cstr:
            col_map[c] = "high"
        elif "low" in cstr:
            col_map[c] = "low"
        elif "close" in cstr:
            col_map[c] = "close"
        elif "volume" in cstr:
            col_map[c] = "volume"
    if not col_map:
        for name in ["Open", "High", "Low", "Close", "Volume"]:
            if name in df.columns:
                col_map[name] = name.lower()
    df = df.rename(columns=col_map)
    for required in ["open", "high", "low", "close"]:
        if required not in df.columns:
            return pd.DataFrame()
    if "volume" not in df.columns:
        df["volume"] = 0
    df = df[["open", "high", "low", "close", "volume"]]
    df = df.astype(float)
    try:
        if df.index.tzinfo is None:
            df.index = df.index.tz_localize(EST, ambiguous="infer")
        else:
            df.index = df.index.tz_convert(EST)
    except Exception:
        pass
    return df


def _session_filter(df: pd.DataFrame, session_ist: bool = False) -> pd.DataFrame:
    """Keep only session bars: EST 7:00–11:00, or IST 8:00 PM–11:30 PM when session_ist=True."""
    if df.empty:
        return df
    idx = df.index
    if idx.tzinfo is None:
        idx = idx.tz_localize(EST, ambiguous="infer")
    idx = idx.tz_convert(IST if session_ist else EST)
    if session_ist:
        minute_of_day = idx.hour * 60 + idx.minute
        mask = (minute_of_day >= IST_SESSION_START_MIN) & (minute_of_day <= IST_SESSION_END_MIN)
    else:
        minute_of_day = idx.hour * 60 + idx.minute
        mask = (minute_of_day >= 7 * 60) & (minute_of_day <= 11 * 60)
    return df.loc[mask].copy()


def fetch_yfinance_1m(symbol: str | None = None, period: str = PERIOD_1M, session_filter: bool = True, session_ist: bool = False) -> pd.DataFrame:
    """Fetch 1m OHLCV from Yahoo Finance. Returns DataFrame with EST index."""
    symbol = symbol or YF_SYMBOLS[0]
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed. Run: pip install yfinance")
        return pd.DataFrame()
    for attempt, api in enumerate(("ticker", "download")):
        try:
            if api == "ticker":
                ticker = yf.Ticker(symbol)
                data = ticker.history(period=period, interval=INTERVAL_1M, prepost=True, auto_adjust=True)
            else:
                data = yf.download(
                    symbol, period=period, interval=INTERVAL_1M,
                    progress=False, auto_adjust=True, prepost=True, threads=False,
                )
            if data is None or data.empty:
                continue
            df = _normalize_ohlcv(data)
            if not df.empty:
                return _session_filter(df, session_ist=session_ist) if session_filter else df
        except Exception as e:
            logger.debug("yfinance 1m %s failed for %s: %s", api, symbol, e)
    return pd.DataFrame()


def fetch_yfinance_15m(symbol: str | None = None, period: str = PERIOD_15M, session_filter: bool = True, session_ist: bool = False) -> pd.DataFrame:
    """Fetch 15m OHLCV from Yahoo Finance. Returns DataFrame with EST index."""
    symbol = symbol or YF_SYMBOLS[0]
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame()
    for attempt, api in enumerate(("ticker", "download")):
        try:
            if api == "ticker":
                ticker = yf.Ticker(symbol)
                data = ticker.history(period=period, interval=INTERVAL_15M, prepost=True, auto_adjust=True)
            else:
                data = yf.download(
                    symbol, period=period, interval=INTERVAL_15M,
                    progress=False, auto_adjust=True, prepost=True, threads=False,
                )
            if data is None or data.empty:
                continue
            df = _normalize_ohlcv(data)
            if not df.empty:
                return _session_filter(df, session_ist=session_ist) if session_filter else df
        except Exception as e:
            logger.debug("yfinance 15m %s failed for %s: %s", api, symbol, e)
    return pd.DataFrame()


def _expand_15m_to_1m(df_15m: pd.DataFrame) -> pd.DataFrame:
    """Expand each 15m bar into 15 x 1m bars (same OHLC) so backtest can run on real levels."""
    if df_15m.empty:
        return pd.DataFrame()
    rows = []
    index = []
    for ts, row in df_15m.iterrows():
        for minute in range(15):
            index.append(ts + pd.Timedelta(minutes=minute))
            rows.append({
                "open": row["open"], "high": row["high"], "low": row["low"],
                "close": row["close"], "volume": row["volume"] / 15,
            })
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(index, tz=df_15m.index.tz))
    df.index.name = "timestamp"
    return df


def fetch_live_backtest_data(
    symbols: tuple[str, ...] = YF_SYMBOLS,
    period_1m: str = PERIOD_1M,
    period_15m: str = PERIOD_15M,
    months: int | None = None,
    session_24_7: bool = False,
    session_ist: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetch 1m and 15m data from Yahoo Finance (free).
    By default session 7–11 EST; session_24_7=True = all hours; session_ist=True = IST 8 PM–11:30 PM.
    Returns (df_1m, df_15m).
    """
    session_filter = not session_24_7
    if months is not None and months >= 1:
        period = "1mo" if months == 1 else "60d"
        for symbol in symbols:
            df_15m = fetch_yfinance_15m(symbol=symbol, period=period, session_filter=session_filter, session_ist=session_ist)
            if not df_15m.empty and len(df_15m) >= 20:
                if len(df_15m) >= 20:
                    df_1m = _expand_15m_to_1m(df_15m)
                    session_note = "24/7" if session_24_7 else ("IST 8PM–11:30PM" if session_ist else "session 7–11 EST")
                    logger.info("Using 15m data (%s) expanded to 1m: %d bars (%s)", period, len(df_1m), session_note)
                    return df_1m, df_15m
        return pd.DataFrame(), pd.DataFrame()

    df_1m = pd.DataFrame()
    df_15m = pd.DataFrame()
    for symbol in symbols:
        df_1m = fetch_yfinance_1m(symbol=symbol, period=period_1m, session_filter=session_filter, session_ist=session_ist)
        if not df_1m.empty:
            df_15m = fetch_yfinance_15m(symbol=symbol, period=period_15m, session_filter=session_filter, session_ist=session_ist)
            if df_15m.empty or len(df_15m) < 20:
                df_15m = df_1m.resample("15min").agg({
                    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
                }).dropna(how="all")
                if session_filter:
                    df_15m = _session_filter(df_15m, session_ist=session_ist)
            break
        logger.warning("No 1m data for %s, trying next symbol.", symbol)
    if df_1m.empty:
        for symbol in symbols:
            df_15m = fetch_yfinance_15m(symbol=symbol, period=period_15m or "60d", session_filter=session_filter, session_ist=session_ist)
            if not df_15m.empty and len(df_15m) >= 20:
                df_1m = _expand_15m_to_1m(df_15m)
                session_note = "24/7" if session_24_7 else ("IST 8PM–11:30PM" if session_ist else "session")
                logger.info("Using 15m data expanded to 1m (symbol=%s, %d bars, %s)", symbol, len(df_1m), session_note)
                break
    if not df_1m.empty and (df_15m.empty or len(df_15m) < 20):
        df_15m = df_1m.resample("15min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        }).dropna(how="all")
        if session_filter:
            df_15m = _session_filter(df_15m, session_ist=session_ist)
    return df_1m, df_15m
