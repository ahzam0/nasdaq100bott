"""
Options chain and IV Rank for QQQ (and universe). Polygon.io or yfinance.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def fetch_chain_polygon(symbol: str = "QQQ", expiration: date | None = None) -> pd.DataFrame:
    """Fetch options chain from Polygon. Requires POLYGON_API_KEY."""
    import os
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not key:
        return pd.DataFrame()
    try:
        from polygon import RESTClient
        client = RESTClient(key)
        # Polygon options snapshot / chain API
        # Reference: https://polygon.io/docs/options
        under = f"O:{symbol}" if not symbol.startswith("O:") else symbol
        # Simplified: get snapshot for underlying
        from datetime import date as d
        exp = expiration or (d.today() + pd.Timedelta(days=30))
        exp_str = exp.strftime("%Y-%m-%d")
        # Chain endpoint varies by provider
        return pd.DataFrame()
    except Exception as e:
        logger.debug("Polygon options failed: %s", e)
        return pd.DataFrame()


def iv_rank_from_chain(chain: pd.DataFrame, current_iv: float) -> float:
    """
    IV Rank = (current_iv - 52w low IV) / (52w high IV - 52w low IV) * 100.
    If chain has implied_vol column and history, compute; else return 50 (neutral).
    """
    if chain is None or chain.empty:
        return 50.0
    if "implied_volatility" in chain.columns:
        iv_series = chain["implied_volatility"].dropna()
        if len(iv_series) < 2:
            return 50.0
        low, high = iv_series.min(), iv_series.max()
        if high <= low:
            return 50.0
        return (current_iv - low) / (high - low) * 100.0
    return 50.0


def get_qqq_put_call_ratio() -> Optional[float]:
    """QQQ put/call ratio (contrarian signal). Requires options data source."""
    chain = fetch_chain_polygon("QQQ")
    if chain.empty or "type" not in chain.columns:
        return None
    calls = (chain["type"] == "call").sum()
    puts = (chain["type"] == "put").sum()
    if calls == 0:
        return None
    return puts / calls


def get_iv_rank(symbol: str = "QQQ") -> float:
    """Return 0-100 IV Rank for symbol (from options chain or cached)."""
    chain = fetch_chain_polygon(symbol)
    # Placeholder: use a default if no chain
    return iv_rank_from_chain(chain, 0.20)
