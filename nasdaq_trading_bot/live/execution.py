"""
NASDAQ execution: limit/market routing, TWAP, iceberg, 3-tranche scaling, fill logging.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

REGULAR_TIMEOUT_SEC = 5
POWER_HOUR_TIMEOUT_SEC = 2
ICEBERG_SHOW_PCT = 0.2
TRANCHES = 3


def order_type_for_session(is_power_hour: bool, is_pre_post: bool) -> str:
    """Pre/post: limit only; regular: limit with timeout; power hour: aggressive limit."""
    if is_pre_post:
        return "limit_only"
    if is_power_hour:
        return "limit_aggressive"
    return "limit_then_market"


def twap_slices(total_qty: int, n_slices: int) -> list[int]:
    """Split order into n_slices (e.g. for TWAP)."""
    if n_slices <= 0:
        return [total_qty]
    base, rem = divmod(total_qty, n_slices)
    return [base + (1 if i < rem else 0) for i in range(n_slices)]


def iceberg_display_qty(total_qty: int, show_pct: float = ICEBERG_SHOW_PCT) -> int:
    """Quantity to show on book (iceberg)."""
    return max(1, int(total_qty * show_pct))


def scale_in_tranches(total_qty: int, n: int = TRANCHES) -> list[int]:
    """33%/33%/34% tranches for scaling in."""
    if n <= 1:
        return [total_qty]
    sizes = twap_slices(total_qty, n)
    return sizes
