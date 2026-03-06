"""
NAS100 metrics: signals/day, win rate, monthly return, profit factor, max DD.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from nas100_elite.config import TARGETS


@dataclass
class NAS100Metrics:
    signals_per_day: float
    win_rate_pct: float
    monthly_return_pct: float
    profit_factor: float
    max_drawdown_pct: float
    total_trades: int
    winners: int
    losers: int
    gross_profit: float
    gross_loss: float
    net_return_pct: float
    sharpe_ratio: float
    best_month_pct: float
    worst_month_pct: float


def compute_nas100_metrics(
    trades: pd.DataFrame,
    equity_curve: pd.Series,
    initial_balance: float,
    trading_days: int,
) -> NAS100Metrics:
    if trades is None or trades.empty:
        return NAS100Metrics(0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    pnl = trades["pnl"]
    total = len(pnl)
    winners = (pnl > 0).sum()
    losers = (pnl <= 0).sum()
    win_rate_pct = (winners / total * 100) if total else 0.0
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(abs(pnl[pnl < 0].sum()))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
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
    return NAS100Metrics(
        signals_per_day=signals_per_day,
        win_rate_pct=win_rate_pct,
        monthly_return_pct=monthly_return_pct,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        total_trades=total,
        winners=winners,
        losers=losers,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_return_pct=net_return_pct,
        sharpe_ratio=float(sharpe_ratio),
        best_month_pct=best_month_pct,
        worst_month_pct=worst_month_pct,
    )


def all_targets_met(m: NAS100Metrics) -> bool:
    return (
        m.signals_per_day >= TARGETS["signals_per_day_min"]
        and m.win_rate_pct >= TARGETS["win_rate_pct_min"]
        and m.monthly_return_pct >= TARGETS["monthly_return_pct_min"]
        and m.profit_factor >= TARGETS["profit_factor_min"]
        and m.max_drawdown_pct <= TARGETS["max_drawdown_pct_max"]
    )
