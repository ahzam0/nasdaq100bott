"""
Key risk management rules for NASDAQ (NAS100/NDX) — non-negotiable.
Apply these in position sizing and execution.
"""

from __future__ import annotations

# --- Risk per trade ---
MAX_RISK_PCT_PER_TRADE = 1.0   # Never risk more than 1–2% per trade
MAX_RISK_PCT_PER_TRADE_HIGH = 2.0

# --- Stops ---
USE_STOP_LOSS_ALWAYS = True    # No exceptions

# --- Diversification ---
# Balance NQ positions with uncorrelated markets (gold, crude, commodities)
DIVERSIFY_WITH = ["gold", "crude_oil", "commodities"]

# --- News blackout ---
# Avoid trading during major news (CPI, FOMC) unless you have a specific news strategy
AVOID_NEWS_EVENTS = True
MAJOR_EVENTS = ["CPI", "FOMC", "NFP", "earnings"]

# --- Reward-to-risk minimum (e.g. multi-timeframe strategy) ---
MIN_REWARD_RISK_RATIO = 3.0   # Aim for 3:1 RR minimum


def risk_pct_per_trade(capital: float, stop_distance: float, price: float) -> float:
    """Return risk as % of capital for given stop distance and price."""
    if not capital or capital <= 0 or not price or price <= 0:
        return 0.0
    risk_per_unit = abs(stop_distance)
    if risk_per_unit <= 0:
        return 0.0
    # Per-share risk as fraction of capital (simplified: 1 share)
    return 100.0 * (risk_per_unit / price) * (price / capital)


def position_size_from_risk(
    capital: float,
    risk_pct: float,
    stop_distance_per_share: float,
    price: float,
) -> float:
    """Shares to trade so that risk_pct of capital is risked (stop_distance in price units)."""
    if capital <= 0 or risk_pct <= 0 or stop_distance_per_share <= 0 or price <= 0:
        return 0.0
    risk_dollars = capital * (risk_pct / 100.0)
    return risk_dollars / stop_distance_per_share
