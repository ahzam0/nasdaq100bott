"""
Position sizing: contracts from max $ risk and stop distance in points.
Includes dynamic sizing based on equity curve performance.
"""

from __future__ import annotations

import logging
from config import TICK_VALUE_USD, MAX_RISK_PER_TRADE_USD

logger = logging.getLogger(__name__)


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
    return max(1, min(n, 10))


def risk_usd_for_trade(
    contracts: int,
    stop_distance_pts: float,
    tick_value: float = TICK_VALUE_USD,
) -> float:
    """Total $ risk for the trade."""
    return contracts * stop_distance_pts * tick_value


def dynamic_risk(
    base_risk_usd: float,
    current_balance: float,
    initial_balance: float = 50_000.0,
    win_streak: int = 0,
    loss_streak: int = 0,
    risk_pct_of_equity: float = 0.75,
    max_risk_usd: float = 500.0,
    min_risk_usd: float = 100.0,
) -> float:
    """
    Dynamic position sizing based on equity and recent performance.

    - Base: risk_pct_of_equity % of current balance (default 0.75%)
    - After 3+ consecutive wins: increase by 25% (momentum)
    - After 2+ consecutive losses: reduce by 40% (protect capital)
    - Clamped between min_risk_usd and max_risk_usd
    """
    equity_risk = current_balance * (risk_pct_of_equity / 100.0)
    risk = max(equity_risk, base_risk_usd)

    if loss_streak >= 2:
        risk *= 0.6
        logger.info("Dynamic sizing: reduced risk after %d consecutive losses", loss_streak)
    elif win_streak >= 3:
        risk *= 1.25
        logger.info("Dynamic sizing: increased risk after %d consecutive wins", win_streak)

    return round(max(min_risk_usd, min(risk, max_risk_usd)), 2)


def get_streak(trade_history: list[dict]) -> tuple[int, int]:
    """Return (win_streak, loss_streak) from most recent trades."""
    if not trade_history:
        return 0, 0
    win_streak = 0
    loss_streak = 0
    for t in reversed(trade_history):
        pnl = t.get("pnl", 0)
        if pnl > 0:
            if loss_streak > 0:
                break
            win_streak += 1
        elif pnl < 0:
            if win_streak > 0:
                break
            loss_streak += 1
        else:
            break
    return win_streak, loss_streak
