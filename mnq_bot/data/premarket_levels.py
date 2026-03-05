"""
Pre-market level computation for NQ/MNQ scalping.

Computes: prior day H/L/C, overnight range, gap size, round numbers.
All from yfinance (free, no API key).
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_TTL = 3600  # 1 hour (levels are static for the session)


@dataclass
class PremarketLevels:
    prior_high: float
    prior_low: float
    prior_close: float
    overnight_high: float
    overnight_low: float
    gap_pts: float             # current price - prior close
    gap_direction: str         # "GAP_UP" | "GAP_DOWN" | "FLAT"
    gap_pct: float
    current_price: float
    round_levels: list[float] = field(default_factory=list)
    bias: str = "NEUTRAL"     # "BULLISH" | "BEARISH" | "NEUTRAL"
    timestamp: float = 0.0


_cache: Optional[PremarketLevels] = None
_cache_ts: float = 0.0
_cache_lock = threading.Lock()


def fetch_premarket_levels() -> PremarketLevels:
    """Compute pre-market levels from NQ=F. Returns cached if fresh."""
    global _cache, _cache_ts
    with _cache_lock:
        if _cache and (time.time() - _cache_ts) < CACHE_TTL:
            return _cache

    try:
        result = _compute_levels()
    except Exception as e:
        logger.warning("Pre-market levels failed: %s", e)
        result = PremarketLevels(
            prior_high=0, prior_low=0, prior_close=0,
            overnight_high=0, overnight_low=0,
            gap_pts=0, gap_direction="FLAT", gap_pct=0,
            current_price=0, timestamp=time.time(),
        )

    with _cache_lock:
        _cache = result
        _cache_ts = time.time()
    return result


def _compute_levels() -> PremarketLevels:
    import yfinance as yf

    ticker = yf.Ticker("NQ=F")

    # Prior day H/L/C from daily data
    daily = ticker.history(period="5d", interval="1d", prepost=False)
    if daily is None or len(daily) < 2:
        raise ValueError("Insufficient daily data for NQ=F")

    prior_day = daily.iloc[-2]
    prior_high = float(prior_day["High"])
    prior_low = float(prior_day["Low"])
    prior_close = float(prior_day["Close"])

    # Overnight range from 1m candles with pre/post market
    intraday = ticker.history(period="2d", interval="1m", prepost=True)
    if intraday is None or intraday.empty:
        raise ValueError("No intraday data for NQ=F")

    current_price = float(intraday["Close"].iloc[-1])

    # Overnight = after prior day close (4pm) to now
    # Use last 16 hours of data as approximation
    overnight_bars = intraday.tail(960)  # ~16 hours of 1-min bars
    overnight_high = float(overnight_bars["High"].max()) if not overnight_bars.empty else prior_high
    overnight_low = float(overnight_bars["Low"].min()) if not overnight_bars.empty else prior_low

    # Gap
    gap_pts = current_price - prior_close
    gap_pct = (gap_pts / prior_close) * 100 if prior_close > 0 else 0

    if gap_pts > 20:
        gap_direction = "GAP_UP"
    elif gap_pts < -20:
        gap_direction = "GAP_DOWN"
    else:
        gap_direction = "FLAT"

    # Round number levels near current price
    base = int(current_price / 50) * 50
    round_levels = [float(base + i * 50) for i in range(-3, 4)]

    # Bias from levels
    if current_price > prior_high and gap_direction == "GAP_UP":
        bias = "BULLISH"
    elif current_price < prior_low and gap_direction == "GAP_DOWN":
        bias = "BEARISH"
    elif current_price > prior_close:
        bias = "BULLISH"
    elif current_price < prior_close:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    logger.info("Pre-market: %s | gap=%+.0f pts (%.2f%%) prior H/L=%.0f/%.0f ON H/L=%.0f/%.0f",
                bias, gap_pts, gap_pct, prior_high, prior_low, overnight_high, overnight_low)

    return PremarketLevels(
        prior_high=prior_high,
        prior_low=prior_low,
        prior_close=prior_close,
        overnight_high=overnight_high,
        overnight_low=overnight_low,
        gap_pts=gap_pts,
        gap_direction=gap_direction,
        gap_pct=gap_pct,
        current_price=current_price,
        round_levels=round_levels,
        bias=bias,
        timestamp=time.time(),
    )
