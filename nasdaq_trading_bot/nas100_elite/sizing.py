"""
Position sizing: Risk = Balance × Risk%. Position size = Risk / (SL points × point value).
"""

from __future__ import annotations

from nas100_elite.config import POINT_VALUE_PER_LOT, SL_POINTS_MIN, SL_POINTS_MAX


def position_size_lots(
    account_balance: float,
    risk_pct: float,
    sl_points: float,
    point_value: float = POINT_VALUE_PER_LOT,
) -> float:
    """
    Lots = (Balance × Risk%) / (SL_points × point_value).
    """
    if sl_points <= 0 or point_value <= 0 or risk_pct <= 0:
        return 0.0
    risk_amount = account_balance * (risk_pct / 100.0)
    size = risk_amount / (sl_points * point_value)
    return max(0.0, size)


def validate_sl_points(sl_points: float) -> bool:
    return SL_POINTS_MIN <= sl_points <= SL_POINTS_MAX
