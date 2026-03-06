"""
Composite score vs 10 targets. Higher = better.
Used to rank candidates and decide when to update best_params.
"""

from __future__ import annotations

from typing import Any, Optional

from backtest.metrics import Metrics, count_targets_met


def composite(metrics: Optional[Metrics], targets: dict[str, Any]) -> float:
    """
    Single composite score: weighted sum of normalized metric achievements.
    Higher is better. Targets from config (sharpe_ratio, max_drawdown_pct, ...).
    """
    if metrics is None:
        return -1e9
    t = targets
    score = 0.0
    # Normalize each metric toward target (0..1 scale)
    if t.get("sharpe_ratio"):
        score += min(1.0, (metrics.sharpe_ratio or 0) / t["sharpe_ratio"])
    if t.get("max_drawdown_pct") is not None:
        score += max(0.0, 1.0 - (metrics.max_drawdown_pct or 100) / max(t["max_drawdown_pct"], 0.01))
    if t.get("win_rate_pct"):
        score += min(1.0, (metrics.win_rate_pct or 0) / t["win_rate_pct"])
    if t.get("cagr_pct"):
        score += min(1.0, (metrics.cagr_pct or 0) / t["cagr_pct"])
    if t.get("profit_factor"):
        score += min(1.0, (metrics.profit_factor or 0) / t["profit_factor"])
    if t.get("sortino_ratio"):
        score += min(1.0, (metrics.sortino_ratio or 0) / t["sortino_ratio"])
    if t.get("calmar_ratio"):
        score += min(1.0, (metrics.calmar_ratio or 0) / t["calmar_ratio"])
    if t.get("annual_volatility_pct") is not None:
        score += max(0.0, 1.0 - (metrics.annual_volatility_pct or 100) / max(t["annual_volatility_pct"], 0.01))
    if t.get("expectancy_per_r"):
        score += min(1.0, (metrics.expectancy_per_r or 0) / t["expectancy_per_r"])
    if t.get("max_consecutive_losses") is not None:
        score += max(0.0, 1.0 - (metrics.max_consecutive_losses or 999) / max(t["max_consecutive_losses"] + 1, 1))
    return score


def count_targets_met_from_metrics(metrics: Optional[Metrics], targets: dict) -> int:
    return count_targets_met(metrics, targets) if metrics else 0


def all_targets_met_from_metrics(metrics: Optional[Metrics], targets: dict) -> bool:
    return count_targets_met_from_metrics(metrics, targets) >= 10
