"""
Entry checklist: ALL conditions must be met before a trade is allowed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, time

from data.calendar import is_near_news
from strategy.setups import ReversalSetup

from config import (
    MIN_RR_RATIO,
    PREMARKET_END,
    PREMARKET_START,
    RTH_END,
    RTH_START,
    USE_ORDERFLOW,
    ORDERFLOW_REQUIRE_CONFIRM,
    ORDERFLOW_MIN_IMBALANCE_LONG,
    ORDERFLOW_MAX_IMBALANCE_SHORT,
    ORDERFLOW_STALE_SEC,
    NO_LONG_FIRST_MINUTES_RTH,
    NO_SHORT_FIRST_MINUTES_RTH,
)

logger = logging.getLogger(__name__)


@dataclass
class ChecklistResult:
    valid: bool
    reason: str  # If not valid, why


def _parse_time(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_trading_window(now_est: datetime) -> bool:
    """Active window: 7:00–9:30 (pre-market) or 9:30–11:00 (RTH first 90 min)."""
    t = now_est.time() if hasattr(now_est, "time") else now_est
    pre_start = _parse_time(PREMARKET_START)
    pre_end = _parse_time(PREMARKET_END)
    rth_start = _parse_time(RTH_START)
    rth_end = _parse_time(RTH_END)
    if pre_start <= t < pre_end:
        return True
    if rth_start <= t < rth_end:
        return True
    return False


def check_rr(setup: ReversalSetup, min_rr_ratio: float | None = None) -> bool:
    """Minimum R/R (default from config)."""
    rr = min_rr_ratio if min_rr_ratio is not None else MIN_RR_RATIO
    if setup.direction == "LONG":
        risk = setup.entry_price - setup.stop_price
        reward1 = setup.target1_price - setup.entry_price
    else:
        risk = setup.stop_price - setup.entry_price
        reward1 = setup.entry_price - setup.target1_price
    if risk <= 0:
        return False
    return (reward1 / risk) >= rr


def check_orderflow(setup: ReversalSetup, orderflow_summary: dict | None) -> ChecklistResult | None:
    """
    If orderflow_summary provided and ORDERFLOW_REQUIRE_CONFIRM, require order flow to confirm direction.
    Live: main passes summary when USE_ORDERFLOW. Backtest: engine can pass candle-based proxy when --use-orderflow-proxy.
    If None or stale, returns None (skip check).
    """
    if not orderflow_summary or not ORDERFLOW_REQUIRE_CONFIRM:
        return None
    age = orderflow_summary.get("age_seconds", 999)
    if age > ORDERFLOW_STALE_SEC:
        return None  # Skip when stale
    imb = orderflow_summary.get("imbalance_ratio", 0.0)
    if setup.direction == "LONG":
        if imb < ORDERFLOW_MIN_IMBALANCE_LONG:
            return ChecklistResult(False, f"Order flow not confirming long (imbalance {imb:.3f} < {ORDERFLOW_MIN_IMBALANCE_LONG})")
    else:
        if imb > ORDERFLOW_MAX_IMBALANCE_SHORT:
            return ChecklistResult(False, f"Order flow not confirming short (imbalance {imb:.3f} > {ORDERFLOW_MAX_IMBALANCE_SHORT})")
    return None  # Pass


def _minutes_since_rth_start(now_est: datetime) -> int | None:
    """Minutes since 9:30 AM EST today, or None if before 9:30."""
    rth_start = _parse_time(RTH_START)
    t = now_est.time() if hasattr(now_est, "time") else now_est
    if t < rth_start:
        return None
    return (now_est.hour - rth_start.hour) * 60 + (now_est.minute - rth_start.minute)


def validate_entry(
    setup: ReversalSetup,
    now_est: datetime,
    trades_taken_today: int,
    max_trades_per_day: int = 3,
    min_rr_ratio: float | None = None,
    orderflow_summary: dict | None = None,
) -> ChecklistResult:
    """
    Validate full entry checklist. Returns ChecklistResult(valid=True) only if ALL pass.
    If USE_ORDERFLOW and orderflow_summary provided, also requires order flow to confirm direction.
    """
    if not in_trading_window(now_est):
        return ChecklistResult(False, "Outside trading window (7:00–9:30 or 9:30–11:00 EST)")

    mins_rth = _minutes_since_rth_start(now_est)
    if mins_rth is not None:
        if setup.direction == "LONG" and NO_LONG_FIRST_MINUTES_RTH > 0 and mins_rth < NO_LONG_FIRST_MINUTES_RTH:
            return ChecklistResult(False, f"No LONG in first {NO_LONG_FIRST_MINUTES_RTH} min after RTH")
        if setup.direction == "SHORT" and NO_SHORT_FIRST_MINUTES_RTH > 0 and mins_rth < NO_SHORT_FIRST_MINUTES_RTH:
            return ChecklistResult(False, f"No SHORT in first {NO_SHORT_FIRST_MINUTES_RTH} min after RTH")

    if trades_taken_today >= max_trades_per_day:
        return ChecklistResult(False, f"Max trades per day reached ({max_trades_per_day})")

    if is_near_news(now_est):
        return ChecklistResult(False, "High-impact news within buffer window")

    rr = min_rr_ratio if min_rr_ratio is not None else MIN_RR_RATIO
    if not check_rr(setup, rr):
        return ChecklistResult(False, f"R/R below minimum {rr}:1")

    of_result = check_orderflow(setup, orderflow_summary)
    if of_result is not None and not of_result.valid:
        return of_result

    return ChecklistResult(True, "All conditions met")
