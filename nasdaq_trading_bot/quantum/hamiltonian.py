"""
Multi-objective loss Hamiltonian with NASDAQ penalties.
H = -w1*Sharpe + w2*MaxDD - w3*WinRate - w4*CAGR - ... + penalties.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


def build_hamiltonian_weights(
    targets: dict[str, Any],
    regime: Optional[str] = None,
) -> dict[str, float]:
    """
    Adaptive weights for Hamiltonian terms. Higher weight = more important.
    Regime-conditional: different weights per market regime.
    """
    w = {
        "sharpe": 1.0,
        "max_drawdown": 1.0,
        "win_rate": 0.8,
        "cagr": 1.0,
        "profit_factor": 0.8,
        "sortino": 0.8,
        "calmar": 0.8,
        "volatility": 0.5,
        "expectancy": 0.8,
        "consec_losses": 0.6,
        "nasdaq_correlation_penalty": 0.3,
        "earnings_period_penalty": 0.2,
    }
    if regime == "NASDAQ_HIGH_VOLATILITY":
        w["volatility"] = 1.2
        w["max_drawdown"] = 1.2
    elif regime == "NASDAQ_BEAR_TREND":
        w["max_drawdown"] = 1.3
        w["consec_losses"] = 1.0
    return w


def _get_metric(metrics: Any, name: str) -> float:
    """Extract metric value from Metrics object or dict."""
    if hasattr(metrics, name):
        v = getattr(metrics, name)
    elif isinstance(metrics, dict):
        v = metrics.get(name)
    else:
        return 0.0
    if v is None:
        return 0.0
    return float(v)


def evaluate_hamiltonian(
    metrics: Any,
    weights: Optional[dict[str, float]] = None,
    targets: Optional[dict[str, Any]] = None,
    regime: Optional[str] = None,
) -> float:
    """
    Multi-objective Hamiltonian value. Lower is better (we minimize).
    Terms: -Sharpe, +MaxDD, -WinRate, -CAGR, -ProfitFactor, -Sortino, +Vol, -Expectancy, +ConsecLosses, -Calmar, +penalties.
    """
    if weights is None:
        weights = build_hamiltonian_weights(targets or {}, regime)
    if targets is None:
        targets = {}

    sharpe = _get_metric(metrics, "sharpe_ratio") or 0.0
    max_dd = _get_metric(metrics, "max_drawdown_pct") or 100.0
    win_rate = _get_metric(metrics, "win_rate_pct") or 0.0
    cagr = _get_metric(metrics, "cagr_pct") or 0.0
    pf = _get_metric(metrics, "profit_factor") or 0.0
    sortino = _get_metric(metrics, "sortino_ratio") or 0.0
    calmar = _get_metric(metrics, "calmar_ratio") or 0.0
    vol = _get_metric(metrics, "annual_volatility_pct") or 100.0
    expectancy = _get_metric(metrics, "expectancy_per_r") or 0.0
    consec = _get_metric(metrics, "max_consecutive_losses") or 999

    # Normalize for scale: targets from config
    t_sharpe = float(targets.get("sharpe_ratio", 5.0))
    t_dd = float(targets.get("max_drawdown_pct", 5.0))
    t_wr = float(targets.get("win_rate_pct", 70.0))
    t_cagr = float(targets.get("cagr_pct", 150.0))
    t_vol = float(targets.get("annual_volatility_pct", 12.0))

    H = 0.0
    H -= weights["sharpe"] * (sharpe / max(t_sharpe, 0.01))
    H += weights["max_drawdown"] * (max_dd / max(t_dd, 0.01))
    H -= weights["win_rate"] * (win_rate / max(t_wr, 1.0))
    H -= weights["cagr"] * (cagr / max(t_cagr, 1.0))
    H -= weights["profit_factor"] * (pf / max(float(targets.get("profit_factor", 3.0)), 0.1))
    H -= weights["sortino"] * (sortino / max(float(targets.get("sortino_ratio", 6.0)), 0.1))
    H += weights["volatility"] * (vol / max(t_vol, 1.0))
    H -= weights["expectancy"] * (expectancy / max(float(targets.get("expectancy_per_r", 2.5)), 0.1))
    H += weights["consec_losses"] * (consec / max(float(targets.get("max_consecutive_losses", 3)), 1))
    H -= weights["calmar"] * (calmar / max(float(targets.get("calmar_ratio", 4.0)), 0.1))

    # Placeholder penalties (would need actual NASDAQ correlation / earnings data)
    H += weights["nasdaq_correlation_penalty"] * 0.0
    H += weights["earnings_period_penalty"] * 0.0

    return float(H)
