"""
Position sizing: contracts from max $ risk and stop distance in points.
"""

from __future__ import annotations

from config import TICK_VALUE_USD, MAX_RISK_PER_TRADE_USD


def contracts_from_risk(
    risk_usd: float,
    stop_distance_pts: float,
    tick_value: float = TICK_VALUE_USD,
) -> int:
    """
    Number of contracts so that (stop_distance_pts * tick_value * contracts) <= risk_usd.
    """
    if stop_distance_pts <= 0:
        return 0
    risk_per_contract = stop_distance_pts * tick_value
    if risk_per_contract <= 0:
        return 0
    n = int(risk_usd / risk_per_contract)
    return max(1, min(n, 10))  # At least 1, cap 10


def risk_usd_for_trade(
    contracts: int,
    stop_distance_pts: float,
    tick_value: float = TICK_VALUE_USD,
) -> float:
    """Total $ risk for the trade."""
    return contracts * stop_distance_pts * tick_value
