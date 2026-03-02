"""
Trade management: stop loss, take profit, breakeven, partial exit.
Trailing milestones and new stop levels.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from config import (
    PARTIAL_EXIT_PERCENT,
    TICK_VALUE_USD,
    TRAIL_AFTER_5R_TICKS,
    TRAIL_MILESTONES,
)

logger = logging.getLogger(__name__)


class TradeStatus(str, Enum):
    OPEN = "open"
    BREAKEVEN = "breakeven"
    PARTIAL_CLOSED = "partial_closed"
    CLOSED = "closed"
    STOPPED = "stopped"


@dataclass
class ActiveTrade:
    direction: str  # LONG | SHORT
    entry: float
    stop: float
    target1: float
    target2: float
    contracts: int
    risk_per_contract_usd: float
    status: TradeStatus = TradeStatus.OPEN
    current_stop: float = 0.0  # Updated when trailing
    last_trailed_r: float = 0.0
    partial_filled: bool = False
    exit_price: float | None = None
    exit_reason: str = ""

    def __post_init__(self):
        if self.current_stop == 0.0:
            self.current_stop = self.stop

    def risk_pts(self) -> float:
        if self.direction == "LONG":
            return self.entry - self.stop
        return self.stop - self.entry

    def risk_usd_per_contract(self) -> float:
        return self.risk_pts() * TICK_VALUE_USD

    def rr_at_price(self, price: float) -> float:
        """R-multiple at given price (1.0 = 1:1)."""
        r_pts = abs(self.entry - self.stop)
        if r_pts <= 0:
            return 0.0
        if self.direction == "LONG":
            return (price - self.entry) / r_pts
        return (self.entry - price) / r_pts

    def pnl_at_price(self, price: float) -> float:
        if self.direction == "LONG":
            pts = price - self.entry
        else:
            pts = self.entry - price
        return pts * TICK_VALUE_USD * self.contracts

    def next_trail_stop_at_r(self, r: float) -> float:
        """Stop price that locks in given R (e.g. +1R)."""
        r_pts = self.risk_pts()
        if self.direction == "LONG":
            return self.entry + r_pts * (r - 1.0)  # breakeven = entry
        return self.entry - r_pts * (r - 1.0)

    def suggested_stop_for_milestone(self, milestone_r: float) -> float:
        """Stop price to lock in milestone_r (e.g. 1.0 = breakeven)."""
        r_pts = self.risk_pts()
        if self.direction == "LONG":
            return self.entry + r_pts * (milestone_r - 1.0)
        return self.entry - r_pts * (milestone_r - 1.0)


def compute_trail_milestones() -> list[float]:
    """R multiples that trigger a trail alert (e.g. 1.0, 1.5, 2.0, ...)."""
    return list(TRAIL_MILESTONES)


def next_milestone_to_trail(current_r: float, last_trailed_r: float) -> float | None:
    """
    Given current R and last trailed R, return next milestone R to trigger (e.g. 1.5 if we're at 1.3).
    """
    milestones = sorted(TRAIL_MILESTONES)
    for m in milestones:
        if m > last_trailed_r and current_r >= m:
            return m
    return None


def stop_for_milestone(trade: ActiveTrade, milestone_r: float) -> float:
    """New stop price when we hit milestone_r."""
    return trade.suggested_stop_for_milestone(milestone_r)


def partial_exit_percent() -> int:
    return PARTIAL_EXIT_PERCENT


def trail_after_5r_ticks() -> int:
    return TRAIL_AFTER_5R_TICKS
