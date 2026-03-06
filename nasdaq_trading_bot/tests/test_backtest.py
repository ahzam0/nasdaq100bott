"""Tests for backtest engine and metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.engine import BacktestEngine, BacktestResult
from backtest.metrics import Metrics, compute_metrics, count_targets_met, all_targets_met


def test_engine_empty():
    engine = BacktestEngine(initial_balance=50_000.0)
    res = engine.run(pd.Series(dtype=float), pd.Series(dtype=float))
    assert res.initial_balance == 50_000.0
    assert res.final_balance == 50_000.0
    assert res.equity_curve is not None


def test_engine_simple_long():
    engine = BacktestEngine(initial_balance=50_000.0)
    idx = pd.date_range("2020-01-01", periods=10, freq="B")
    prices = pd.Series(100.0 + np.arange(10) * 2, index=idx)
    signals = pd.Series(0, index=idx)
    signals.iloc[1] = 1
    signals.iloc[5] = 0
    res = engine.run(prices, signals)
    assert res.metrics is not None
    assert res.final_balance != 50_000.0 or res.metrics.total_trades == 0


def test_count_targets_met():
    m = Metrics(
        sharpe_ratio=6.0, sortino_ratio=7.0, calmar_ratio=5.0, cagr_pct=160.0,
        max_drawdown_pct=4.0, max_drawdown_usd=2000.0, win_rate_pct=72.0,
        profit_factor=3.5, total_return_pct=100.0, annual_volatility_pct=10.0,
        expectancy_per_r=3.0, max_consecutive_losses=2, total_trades=50,
        winners=36, losers=14, nasdaq_alpha=5.0, tech_beta=1.0,
    )
    t = {"sharpe_ratio": 5.0, "max_drawdown_pct": 5.0, "win_rate_pct": 70.0, "cagr_pct": 150.0,
         "profit_factor": 3.0, "sortino_ratio": 6.0, "calmar_ratio": 4.0, "annual_volatility_pct": 12.0,
         "expectancy_per_r": 2.5, "max_consecutive_losses": 3}
    assert count_targets_met(m, t) >= 9
    assert all_targets_met(m, t)
