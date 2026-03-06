"""
Weekly NASDAQ-100 + Next Gen 100 universe ranking.
Top 20 by momentum, liquidity, volatility, short interest, earnings proximity, institutional flow.
Rebalance every Monday pre-market.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# NASDAQ-100 + Next Gen 100 component symbols (subset for demo; extend to full 200)
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA", "AVGO", "ASML",
    "AMD", "SMCI", "MSTR", "PLTR", "CRWD", "SNOW", "NET", "DDOG", "MDB",
    "INTC", "QCOM", "AMAT", "LRCX", "KLAC", "MRVL", "TSM", "ARM", "MPWR",
    "ORCL", "CRM", "WDAY", "NOW", "ZS", "PANW",
    "AMGN", "GILD", "BIIB", "REGN", "VRTX", "ILMN", "MRNA",
    "QQQ", "TQQQ", "SQQQ", "QLD",
]


def fetch_quote(symbol: str) -> dict:
    """Fetch current quote (yfinance). Returns dict with price, volume, etc."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        info = t.info
        h = t.history(period="5d")
        return {
            "symbol": symbol,
            "price": info.get("currentPrice") or info.get("regularMarketPrice") or (h["Close"].iloc[-1] if not h.empty else None),
            "volume": info.get("volume") or (h["Volume"].iloc[-1] if not h.empty else 0),
            "avg_volume": info.get("averageVolume") or (h["Volume"].mean() if not h.empty else 0),
            "market_cap": info.get("marketCap"),
            "short_ratio": info.get("shortRatio"),
            "beta": info.get("beta"),
        }
    except Exception as e:
        logger.debug("Quote %s: %s", symbol, e)
        return {"symbol": symbol, "price": None, "volume": 0, "avg_volume": 0, "market_cap": None, "short_ratio": None, "beta": None}


def momentum_score(symbol: str, lookback_days: int = 20) -> float:
    """Price momentum (e.g. 20-day return). Higher = stronger momentum."""
    try:
        import yfinance as yf
        df = yf.Ticker(symbol).history(period=f"{lookback_days+5}d")
        if df is None or len(df) < lookback_days:
            return 0.0
        df = df.sort_index()
        start = df["Close"].iloc[-lookback_days]
        end = df["Close"].iloc[-1]
        if start and start > 0:
            return (end / start - 1.0) * 100
    except Exception:
        pass
    return 0.0


def liquidity_score(avg_volume: float, min_volume: float = 1_000_000) -> float:
    """0-100 scale; 1M+ volume = 100."""
    if avg_volume is None or avg_volume <= 0:
        return 0.0
    return min(100.0, (avg_volume / min_volume) * 50.0)


def volatility_score(series: pd.Series, window: int = 20) -> float:
    """Annualized volatility (for ranking)."""
    if series is None or len(series) < window:
        return 0.0
    ret = series.pct_change().dropna()
    if len(ret) < window:
        return 0.0
    return ret.tail(window).std() * (252 ** 0.5) * 100 if ret.std() > 0 else 0.0


def rank_universe(
    symbols: list[str] | None = None,
    as_of: date | None = None,
    top_n: int = 20,
    lookback_days: int = 20,
) -> list[str]:
    """
    Rank full universe by momentum, liquidity, volatility, short interest.
    Returns top_n symbols for active trading.
    """
    symbols = symbols or DEFAULT_UNIVERSE
    as_of = as_of or date.today()
    rows = []
    for sym in symbols:
        q = fetch_quote(sym)
        mom = momentum_score(sym, lookback_days)
        liq = liquidity_score(q.get("avg_volume") or 0)
        rows.append({
            "symbol": sym,
            "momentum": mom,
            "liquidity": liq,
            "volume": q.get("volume") or 0,
            "avg_volume": q.get("avg_volume") or 0,
            "market_cap": q.get("market_cap") or 0,
            "short_ratio": q.get("short_ratio") or 0,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return symbols[:top_n]
    # Composite: momentum weight 0.5, liquidity 0.3, penalize very low volume
    df["score"] = (
        df["momentum"].fillna(0) * 0.5
        + df["liquidity"].fillna(0) * 0.3
        + (df["avg_volume"].fillna(0) / 1e6).clip(0, 10) * 2.0
    )
    df = df[df["avg_volume"] >= 500_000].sort_values("score", ascending=False)
    out = df["symbol"].head(top_n).tolist()
    return out if out else symbols[:top_n]


def get_active_universe(
    rebalance_weekday: int = 0,
    top_n: int = 20,
) -> list[str]:
    """
    Return current week's active universe (top_n).
    Rebalance on rebalance_weekday (0=Monday).
    """
    today = date.today()
    return rank_universe(top_n=top_n)


def next_rebalance_date(rebalance_weekday: int = 0) -> date:
    """Next Monday (or given weekday) on or after today."""
    d = date.today()
    w = d.weekday()
    days_ahead = (rebalance_weekday - w) % 7
    if days_ahead == 0:
        return d
    return d + timedelta(days=days_ahead)
