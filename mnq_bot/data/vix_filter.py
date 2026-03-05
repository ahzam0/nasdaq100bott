"""
VIX volatility filter for MNQ trading bot.
Fetches ^VIX from Yahoo Finance, caches for 5 minutes, provides block/reduce/normal actions.
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_TTL_SEC = 300
_cached_vix: float | None = None
_cache_time: float = 0.0


def get_vix() -> float | None:
    """Return current VIX value (cached for 5 minutes)."""
    global _cached_vix, _cache_time
    now = time.monotonic()
    if _cached_vix is not None and (now - _cache_time) < _CACHE_TTL_SEC:
        return _cached_vix
    try:
        import yfinance as yf
        ticker = yf.Ticker("^VIX")
        hist = ticker.history(period="1d", interval="1m")
        if hist.empty:
            hist = ticker.history(period="5d", interval="1d")
        if hist.empty:
            logger.warning("VIX: no history from yfinance")
            return None
        val = float(hist["Close"].iloc[-1])
        if val <= 0 or val > 200:
            logger.warning("VIX: implausible value %.2f", val)
            return None
        _cached_vix = val
        _cache_time = now
        return val
    except Exception as e:
        logger.warning("VIX fetch failed: %s", e)
        return None


def vix_check(
    vix_threshold: float = 30.0,
    reduce_threshold: float = 25.0,
) -> dict[str, Any]:
    """
    Check VIX against thresholds. Returns action dict:
    - block: VIX > vix_threshold
    - reduce: VIX > reduce_threshold (and <= vix_threshold)
    - normal: otherwise, or if fetch failed
    """
    vix = get_vix()
    if vix is None:
        return {"action": "normal", "vix": None, "reason": "Could not fetch VIX"}
    if vix > vix_threshold:
        return {"action": "block", "vix": vix, "reason": "VIX too high"}
    if vix > reduce_threshold:
        return {"action": "reduce", "vix": vix, "factor": 0.5, "reason": "VIX elevated"}
    return {"action": "normal", "vix": vix}
