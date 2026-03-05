"""
NASDAQ market internals: advance/decline, TICK proxy, TRIN proxy.

Computes breadth from NASDAQ-100 component stocks via yfinance batch
download (single call for all ~100 stocks). 100% free, no API key.
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# NASDAQ-100 components (top ~50 by NQ weight -- covers >85% of index)
NDX_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "AVGO",
    "TSLA", "COST", "NFLX", "AMD", "ADBE", "PEP", "QCOM", "TMUS",
    "CSCO", "INTC", "INTU", "CMCSA", "TXN", "AMGN", "HON", "AMAT",
    "ISRG", "BKNG", "LRCX", "SBUX", "VRTX", "MU", "ADI", "MDLZ",
    "GILD", "PANW", "REGN", "KLAC", "SNPS", "CDNS", "MELI", "MAR",
    "PYPL", "CRWD", "CTAS", "ABNB", "ORLY", "MRVL", "FTNT", "DASH",
    "WDAY", "CEG",
]

CACHE_TTL = 300  # 5 minutes


@dataclass
class MarketInternals:
    adl: int                  # advance - decline count
    tick_proxy: int           # uptick stocks - downtick stocks (last bar)
    trin: float               # TRIN proxy
    breadth_pct: float        # % of stocks advancing (0-100)
    advancing: int
    declining: int
    bias: str                 # "BULLISH" | "BEARISH" | "NEUTRAL"
    timestamp: float = 0.0


_cache: Optional[MarketInternals] = None
_cache_ts: float = 0.0
_cache_lock = threading.Lock()


def fetch_market_internals() -> MarketInternals:
    """Compute NASDAQ breadth internals. Returns cached if fresh."""
    global _cache, _cache_ts
    with _cache_lock:
        if _cache and (time.time() - _cache_ts) < CACHE_TTL:
            return _cache

    try:
        result = _compute_internals()
    except Exception as e:
        logger.warning("Market internals failed: %s", e)
        result = MarketInternals(
            adl=0, tick_proxy=0, trin=1.0, breadth_pct=50.0,
            advancing=0, declining=0, bias="NEUTRAL", timestamp=time.time(),
        )

    with _cache_lock:
        _cache = result
        _cache_ts = time.time()
    return result


def _compute_internals() -> MarketInternals:
    import yfinance as yf
    import pandas as pd

    symbols_str = " ".join(NDX_SYMBOLS)
    data = yf.download(symbols_str, period="2d", interval="1m",
                       progress=False, auto_adjust=True, threads=True,
                       group_by="ticker")

    if data is None or data.empty:
        raise ValueError("No data from yfinance batch download")

    advancing = 0
    declining = 0
    adv_volume = 0
    dec_volume = 0
    upticks = 0
    downticks = 0

    for sym in NDX_SYMBOLS:
        try:
            if sym not in data.columns.get_level_values(0):
                continue
            df = data[sym].dropna(how="all")
            if df.empty or len(df) < 2:
                continue

            last_close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            last_vol = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0

            if last_close > prev_close:
                advancing += 1
                adv_volume += last_vol
                upticks += 1
            elif last_close < prev_close:
                declining += 1
                dec_volume += last_vol
                downticks += 1
        except Exception:
            continue

    total = advancing + declining
    if total == 0:
        return MarketInternals(
            adl=0, tick_proxy=0, trin=1.0, breadth_pct=50.0,
            advancing=0, declining=0, bias="NEUTRAL", timestamp=time.time(),
        )

    adl = advancing - declining
    tick_proxy = upticks - downticks
    breadth_pct = (advancing / total) * 100

    # TRIN = (Adv/Dec) / (AdvVol/DecVol)
    if declining > 0 and dec_volume > 0:
        ad_ratio = advancing / declining
        vol_ratio = adv_volume / dec_volume if dec_volume > 0 else 1.0
        trin = ad_ratio / vol_ratio if vol_ratio > 0 else 1.0
    else:
        trin = 0.5 if advancing > declining else 1.5

    # Determine bias
    if breadth_pct >= 70:
        bias = "BULLISH"
    elif breadth_pct <= 30:
        bias = "BEARISH"
    elif trin < 0.8 and adl > 10:
        bias = "BULLISH"
    elif trin > 1.2 and adl < -10:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    logger.info("Market internals: %s | ADL=%+d TICK=%+d TRIN=%.2f breadth=%.0f%%",
                bias, adl, tick_proxy, trin, breadth_pct)

    return MarketInternals(
        adl=adl, tick_proxy=tick_proxy, trin=trin, breadth_pct=breadth_pct,
        advancing=advancing, declining=declining, bias=bias, timestamp=time.time(),
    )
