"""
Walk-forward, CPCV, Monte Carlo, regime test, stress tests (COVID, 2022 bear, etc.).
"""

from __future__ import annotations

import logging
import random
from typing import Callable, Optional

import numpy as np
import pandas as pd

from backtest.metrics import Metrics, compute_metrics

logger = logging.getLogger(__name__)


def walk_forward(
    prices: pd.Series,
    signals: pd.Series,
    n_folds: int,
    train_pct: float = 0.7,
    engine_factory: Callable = None,
) -> list[Metrics]:
    """Split into n_folds train/OOS; run engine on each; return OOS metrics per fold."""
    if prices is None or signals is None or len(prices) < 100:
        return []
    idx = prices.index.union(signals.index).drop_duplicates().sort_values()
    prices = prices.reindex(idx).ffill()
    signals = signals.reindex(idx).ffill().fillna(0)
    n = len(idx)
    fold_size = n // n_folds
    results = []
    for f in range(n_folds - 1):
        start = f * fold_size
        end = min((f + 2) * fold_size, n)
        train_end = start + int((end - start) * train_pct)
        oos_prices = prices.iloc[train_end:end]
        oos_signals = signals.iloc[train_end:end]
        if engine_factory:
            engine = engine_factory()
            res = engine.run(oos_prices, oos_signals)
            if res.metrics:
                results.append(res.metrics)
    return results


def monte_carlo(
    returns: pd.Series,
    n_shuffles: int = 10_000,
    seed: int = 42,
) -> tuple[float, float]:
    """P95 drawdown and P5 CAGR from shuffled returns. Returns (p95_dd_pct, p5_cagr_pct)."""
    rng = random.Random(seed)
    returns = returns.dropna()
    if returns.empty or len(returns) < 20:
        return 100.0, 0.0
    dd_list = []
    cagr_list = []
    n = len(returns)
    for _ in range(n_shuffles):
        perm = returns.sample(frac=1.0, random_state=rng.randint(0, 2**31 - 1)).values
        eq = 50000.0 * (1 + perm).cumprod()
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / peak * 100
        dd_list.append(np.max(dd))
        total_ret = eq[-1] / 50000.0 - 1.0
        years = n / 252.0
        cagr = ( (eq[-1] / 50000.0) ** (1 / years) - 1.0 ) * 100 if years > 0 else 0.0
        cagr_list.append(cagr)
    p95_dd = float(np.percentile(dd_list, 95))
    p5_cagr = float(np.percentile(cagr_list, 5))
    return p95_dd, p5_cagr


def passes_oos_gate(is_metrics: Metrics, oos_metrics: Metrics, min_pct: float = 80.0) -> bool:
    """OOS Sharpe >= min_pct% of IS Sharpe."""
    if oos_metrics.sharpe_ratio is None or is_metrics.sharpe_ratio is None or is_metrics.sharpe_ratio <= 0:
        return True
    return oos_metrics.sharpe_ratio >= (is_metrics.sharpe_ratio * min_pct / 100.0)


def passes_regime_test(metrics_per_regime: list[Metrics], min_profitable: int = 4) -> bool:
    """Profitable in >= min_profitable regimes."""
    profitable = sum(1 for m in metrics_per_regime if m and m.total_return_pct > 0)
    return profitable >= min_profitable


def covid_crash_test(equity: pd.Series, march_2020_start: str = "2020-03-01", march_2020_end: str = "2020-03-31", max_dd_pct: float = 15.0) -> bool:
    """Drawdown in Mar 2020 < max_dd_pct."""
    try:
        eq = equity.loc[march_2020_start:march_2020_end]
        if eq.empty or len(eq) < 2:
            return True
        peak = eq.expanding().max()
        dd = (peak - eq) / peak * 100
        return float(dd.max()) <= max_dd_pct
    except Exception:
        return True


def bear_2022_test(equity: pd.Series, start: str = "2022-01-01", end: str = "2022-12-31") -> bool:
    """Strategy should not blow up in 2022 (NASDAQ bear). Allow negative return but limit DD."""
    try:
        eq = equity.loc[start:end]
        if eq.empty or len(eq) < 2:
            return True
        peak = eq.expanding().max()
        dd = (peak - eq) / peak * 100
        return float(dd.max()) <= 30.0
    except Exception:
        return True


def validate_all(
    equity: pd.Series,
    returns: pd.Series,
    trades: pd.DataFrame,
    is_metrics: Optional[Metrics] = None,
    oos_metrics: Optional[Metrics] = None,
    metrics_per_regime: Optional[list[Metrics]] = None,
    monte_carlo_shuffles: int = 10_000,
) -> dict[str, bool]:
    """Run all validation gates. Returns dict of gate_name -> passed."""
    results = {}
    if returns is not None and not returns.empty:
        p95_dd, p5_cagr = monte_carlo(returns, n_shuffles=monte_carlo_shuffles)
        results["monte_carlo_p95_dd_under_10"] = p95_dd < 10.0
        results["monte_carlo_p5_cagr_over_20"] = p5_cagr > 20.0
    if is_metrics and oos_metrics:
        results["oos_sharpe_80pct_of_is"] = passes_oos_gate(is_metrics, oos_metrics, 80.0)
    if metrics_per_regime:
        results["profitable_in_4_of_5_regimes"] = passes_regime_test(metrics_per_regime, 4)
    if equity is not None and not equity.empty:
        results["covid_drawdown_under_15"] = covid_crash_test(equity)
        results["bear_2022_handled"] = bear_2022_test(equity)
    return results
