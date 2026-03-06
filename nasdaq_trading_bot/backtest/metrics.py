"""
All 25+ metrics including NASDAQ-specific: Sharpe, Sortino, Calmar, CAGR,
max DD, win rate, profit factor, expectancy, consecutive losses, NASDAQ alpha, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class Metrics:
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    cagr_pct: float
    max_drawdown_pct: float
    max_drawdown_usd: float
    win_rate_pct: float
    profit_factor: float
    total_return_pct: float
    annual_volatility_pct: float
    expectancy_per_r: float
    max_consecutive_losses: int
    total_trades: int
    winners: int
    losers: int
    nasdaq_alpha: float  # excess return vs benchmark (QQQ)
    tech_beta: float
    # Placeholders for earnings/power hour etc.
    earnings_pl_pct: float = 0.0
    power_hour_pl_pct: float = 0.0


def _annualization_factor(trading_days: int) -> float:
    if trading_days <= 0:
        return 1.0
    return (252 / trading_days) ** 0.5


def compute_metrics(
    returns: pd.Series,
    equity: pd.Series,
    trades: pd.DataFrame,
    benchmark_returns: Optional[pd.Series] = None,
    initial_balance: float = 50_000.0,
) -> Metrics:
    """
    Compute full metrics from equity curve and trades.
    returns: period returns (e.g. daily)
    equity: equity curve (same index as returns)
    trades: DataFrame with columns [pnl, exit_reason] or at least pnl
    """
    if returns is None or returns.empty:
        returns = pd.Series(dtype=float)
    if equity is None or equity.empty:
        equity = pd.Series([initial_balance], dtype=float)

    n = len(returns)
    trading_days = n
    ann_factor = _annualization_factor(trading_days)

    # Total return
    total_return_pct = (equity.iloc[-1] / initial_balance - 1.0) * 100 if initial_balance else 0.0
    # CAGR
    years = trading_days / 252.0 if trading_days else 0
    cagr_pct = ( (equity.iloc[-1] / initial_balance) ** (1 / years) - 1.0 ) * 100 if years > 0 and initial_balance else 0.0

    # Volatility (annualized)
    vol = returns.std()
    annual_volatility_pct = vol * ann_factor * 100 if vol and not np.isnan(vol) else 0.0

    # Sharpe (excess return / vol; no risk-free for simplicity)
    mean_ret = returns.mean()
    sharpe_ratio = (mean_ret / vol * ann_factor) if vol and vol > 0 and not np.isnan(vol) else 0.0

    # Sortino (downside dev)
    downside = returns[returns < 0]
    down_std = downside.std() if len(downside) > 0 else 0.0
    sortino_ratio = (mean_ret / down_std * ann_factor) if down_std and down_std > 0 else 0.0

    # Max drawdown
    peak = equity.expanding().max()
    dd = peak - equity
    max_dd_usd = dd.max() if not dd.empty else 0.0
    max_dd_pct = (max_dd_usd / peak.max() * 100) if peak.max() and peak.max() > 0 else 0.0

    # Calmar
    calmar_ratio = (cagr_pct / 100.0) / (max_dd_pct / 100.0) if max_dd_pct and max_dd_pct > 0 else 0.0

    # Trades
    if trades is None or trades.empty:
        win_rate_pct = 0.0
        profit_factor = 0.0
        expectancy_per_r = 0.0
        max_consecutive_losses = 0
        total_trades = 0
        winners = 0
        losers = 0
    else:
        pnl = trades["pnl"] if "pnl" in trades.columns else trades.iloc[:, 0]
        total_trades = len(pnl)
        winners = (pnl > 0).sum()
        losers = (pnl <= 0).sum()
        win_rate_pct = (winners / total_trades * 100) if total_trades else 0.0
        gross_profit = pnl[pnl > 0].sum()
        gross_loss = abs(pnl[pnl < 0].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss and gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
        # Expectancy per $1 risked (simplified: avg pnl per trade / initial risk unit)
        expectancy_per_r = (pnl.mean() / 100.0) if total_trades else 0.0  # scale as needed
        # Consecutive losses
        consec = 0
        max_consec = 0
        for v in pnl:
            if v <= 0:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0
        max_consecutive_losses = max_consec
    # NASDAQ alpha (vs QQQ)
    nasdaq_alpha = 0.0
    tech_beta = 1.0
    if benchmark_returns is not None and not benchmark_returns.empty and len(returns) == len(benchmark_returns):
        cov = returns.cov(benchmark_returns)
        var_b = benchmark_returns.var()
        tech_beta = (cov / var_b) if var_b and var_b > 0 else 1.0
        bench_ret = benchmark_returns.mean() * 252 * 100
        nasdaq_alpha = cagr_pct - bench_ret

    return Metrics(
        sharpe_ratio=float(sharpe_ratio),
        sortino_ratio=float(sortino_ratio),
        calmar_ratio=float(calmar_ratio),
        cagr_pct=float(cagr_pct),
        max_drawdown_pct=float(max_dd_pct),
        max_drawdown_usd=float(max_dd_usd),
        win_rate_pct=float(win_rate_pct),
        profit_factor=float(profit_factor),
        total_return_pct=float(total_return_pct),
        annual_volatility_pct=float(annual_volatility_pct),
        expectancy_per_r=float(expectancy_per_r),
        max_consecutive_losses=int(max_consecutive_losses),
        total_trades=int(total_trades),
        winners=int(winners),
        losers=int(losers),
        nasdaq_alpha=float(nasdaq_alpha),
        tech_beta=float(tech_beta),
    )


def count_targets_met(m: Metrics, targets: dict) -> int:
    """Return how many of the 10 targets are met."""
    t = targets
    count = 0
    if m.sharpe_ratio >= t.get("sharpe_ratio", 5.0):
        count += 1
    if m.max_drawdown_pct <= t.get("max_drawdown_pct", 5.0):
        count += 1
    if m.win_rate_pct >= t.get("win_rate_pct", 70.0):
        count += 1
    if m.cagr_pct >= t.get("cagr_pct", 150.0):
        count += 1
    if m.profit_factor >= t.get("profit_factor", 3.0):
        count += 1
    if m.sortino_ratio >= t.get("sortino_ratio", 6.0):
        count += 1
    if m.calmar_ratio >= t.get("calmar_ratio", 4.0):
        count += 1
    if m.annual_volatility_pct <= t.get("annual_volatility_pct", 12.0):
        count += 1
    if m.expectancy_per_r >= t.get("expectancy_per_r", 2.5):
        count += 1
    if m.max_consecutive_losses <= t.get("max_consecutive_losses", 3):
        count += 1
    return count


def all_targets_met(m: Metrics, targets: dict) -> bool:
    return count_targets_met(m, targets) >= 10
