"""
Elite system metrics: signals/day, win rate, monthly return, profit factor, max drawdown.
Plus: total trades, avg win/loss, Sharpe, best/worst month.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd


@dataclass
class EliteMetrics:
    signals_per_day: float
    win_rate_pct: float
    monthly_return_pct: float
    profit_factor: float
    max_drawdown_pct: float
    total_trades: int
    winners: int
    losers: int
    avg_win: float
    avg_loss: float
    gross_profit: float
    gross_loss: float
    sharpe_ratio: float
    best_month_pct: float
    worst_month_pct: float
    net_return_pct: float


def compute_elite_metrics(
    trades: pd.DataFrame,
    equity_curve: pd.Series,
    initial_balance: float,
    trading_days: int,
) -> EliteMetrics:
    """
    trades: DataFrame with columns [entry_time, exit_time, pnl, result ('win'|'loss')]
    equity_curve: series of equity per bar
    trading_days: number of trading days in period
    """
    if trades is None or trades.empty:
        return EliteMetrics(
            signals_per_day=0.0, win_rate_pct=0.0, monthly_return_pct=0.0, profit_factor=0.0,
            max_drawdown_pct=0.0, total_trades=0, winners=0, losers=0, avg_win=0.0, avg_loss=0.0,
            gross_profit=0.0, gross_loss=0.0, sharpe_ratio=0.0, best_month_pct=0.0, worst_month_pct=0.0,
            net_return_pct=0.0,
        )
    pnl = trades["pnl"] if "pnl" in trades.columns else trades.iloc[:, 0]
    total = len(pnl)
    winners = (pnl > 0).sum()
    losers = (pnl <= 0).sum()
    win_rate_pct = (winners / total * 100) if total else 0.0
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(abs(pnl[pnl < 0].sum()))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
    avg_win = (pnl[pnl > 0].mean()) if winners else 0.0
    avg_loss = (pnl[pnl < 0].mean()) if losers else 0.0

    trading_days = max(1, trading_days)
    signals_per_day = total / trading_days

    final = float(equity_curve.iloc[-1]) if equity_curve is not None and len(equity_curve) else initial_balance
    net_return_pct = (final / initial_balance - 1.0) * 100 if initial_balance else 0.0
    months = trading_days / 21.0
    monthly_return_pct = ((final / initial_balance) ** (1 / months) - 1.0) * 100 if months > 0 else 0.0

    if equity_curve is not None and len(equity_curve) > 1:
        peak = equity_curve.expanding().max()
        dd = (peak - equity_curve) / peak * 100
        max_drawdown_pct = float(dd.max())
        returns = equity_curve.pct_change().dropna()
        sharpe_ratio = (returns.mean() / returns.std() * (252 ** 0.5)) if returns.std() > 0 else 0.0
        try:
            monthly_returns = equity_curve.resample("ME").last().pct_change().dropna() * 100
            best_month_pct = float(monthly_returns.max()) if len(monthly_returns) else 0.0
            worst_month_pct = float(monthly_returns.min()) if len(monthly_returns) else 0.0
        except Exception:
            best_month_pct = 0.0
            worst_month_pct = 0.0
    else:
        max_drawdown_pct = 0.0
        sharpe_ratio = 0.0
        best_month_pct = 0.0
        worst_month_pct = 0.0

    return EliteMetrics(
        signals_per_day=signals_per_day,
        win_rate_pct=win_rate_pct,
        monthly_return_pct=monthly_return_pct,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        total_trades=total,
        winners=winners,
        losers=losers,
        avg_win=float(avg_win),
        avg_loss=float(avg_loss),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        sharpe_ratio=float(sharpe_ratio),
        best_month_pct=best_month_pct,
        worst_month_pct=worst_month_pct,
        net_return_pct=net_return_pct,
    )


def all_targets_met(m: EliteMetrics, targets: dict) -> bool:
    return (
        m.signals_per_day >= targets.get("signals_per_day_min", 1.0)
        and m.win_rate_pct >= targets.get("win_rate_pct_min", 70.0)
        and m.monthly_return_pct >= targets.get("monthly_return_pct_min", 40.0)
        and m.profit_factor >= targets.get("profit_factor_min", 2.0)
        and m.max_drawdown_pct <= targets.get("max_drawdown_pct_max", 15.0)
    )


def backtest_report(m: EliteMetrics) -> str:
    return f"""
Total trades: {m.total_trades}
Win rate: {m.win_rate_pct:.1f}%
Average win size: {m.avg_win:.2f}  |  Average loss size: {m.avg_loss:.2f}
Profit factor: {m.profit_factor:.2f}
Maximum drawdown: {m.max_drawdown_pct:.1f}%
Monthly return: {m.monthly_return_pct:.1f}%
Sharpe ratio: {m.sharpe_ratio:.2f}
Best month: {m.best_month_pct:.1f}%  |  Worst month: {m.worst_month_pct:.1f}%
Signals per day: {m.signals_per_day:.2f}
Net return: {m.net_return_pct:.1f}%
"""
