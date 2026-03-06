"""
NAS100 v3.0 backtest: 1.5/1/0.5% risk by trade #, 2/6/12% circuit breakers,
max 1 open trade, spread 1pt, slippage 2pt. TP1 30%, TP2 50%, TP3 20% trail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Tuple

import numpy as np
import pandas as pd

from nas100_v3.config import (
    CIRCUIT_BREAKERS_V3,
    POINT_VALUE,
    SPREAD_PTS,
    SLIPPAGE_PTS,
)


@dataclass
class BacktestResultV3:
    equity_curve: pd.Series
    trades: pd.DataFrame
    initial_balance: float
    final_balance: float
    metrics: dict
    circuit_breakers_triggered: List[str]


def _run_one_trade(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    idx: pd.DatetimeIndex,
    entry_bar: int,
    direction: str,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    trail_pts: float,
    cost_pts: float,
) -> Tuple[float, int, str]:
    """
    Simulate one trade with 30% at TP1, 50% at TP2, 20% trail.
    Returns (pnl_pts, exit_bar, exit_reason).
    """
    n = len(close)
    if direction == "BUY":
        pnl_pts = -cost_pts
        closed_30 = False
        closed_50 = False
        trail_level = -np.inf
        exit_bar = entry_bar
        exit_reason = "eod"
        for j in range(entry_bar, min(entry_bar + 200, n)):
            if low[j] <= sl:
                # Full loss
                pnl_pts = (sl - entry) - cost_pts
                exit_bar = j
                exit_reason = "sl"
                break
            if not closed_30 and high[j] >= tp1:
                pnl_pts += 0.3 * (tp1 - entry)
                closed_30 = True
                sl = entry  # breakeven
            if not closed_50 and high[j] >= tp2:
                pnl_pts += 0.5 * (tp2 - entry)
                closed_50 = True
            if closed_30:
                trail_level = max(trail_level, high[j] - trail_pts)
            if closed_50 and closed_30:
                if low[j] <= trail_level:
                    pnl_pts += 0.2 * (trail_level - entry)
                    exit_bar = j
                    exit_reason = "trail"
                    break
        else:
            exit_price = close[min(entry_bar + 199, n - 1)]
            if closed_30 and closed_50:
                pnl_pts += 0.2 * (exit_price - entry)
            elif closed_30:
                pnl_pts += 0.5 * (exit_price - entry)
                pnl_pts += 0.2 * (exit_price - entry)
            else:
                pnl_pts = (exit_price - entry) - cost_pts
            exit_bar = min(entry_bar + 199, n - 1)
    else:
        pnl_pts = -cost_pts
        closed_30 = False
        closed_50 = False
        trail_level = np.inf
        exit_bar = entry_bar
        exit_reason = "eod"
        for j in range(entry_bar, min(entry_bar + 200, n)):
            if high[j] >= sl:
                pnl_pts = (entry - sl) - cost_pts
                exit_bar = j
                exit_reason = "sl"
                break
            if not closed_30 and low[j] <= tp1:
                pnl_pts += 0.3 * (entry - tp1)
                closed_30 = True
                sl = entry
            if not closed_50 and low[j] <= tp2:
                pnl_pts += 0.5 * (entry - tp2)
                closed_50 = True
            if closed_30:
                trail_level = min(trail_level, low[j] + trail_pts)
            if closed_50 and closed_30:
                if high[j] >= trail_level:
                    pnl_pts += 0.2 * (entry - trail_level)
                    exit_bar = j
                    exit_reason = "trail"
                    break
        else:
            exit_price = close[min(entry_bar + 199, n - 1)]
            if closed_30 and closed_50:
                pnl_pts += 0.2 * (entry - exit_price)
            elif closed_30:
                pnl_pts += 0.5 * (entry - exit_price)
                pnl_pts += 0.2 * (entry - exit_price)
            else:
                pnl_pts = (entry - exit_price) - cost_pts
            exit_bar = min(entry_bar + 199, n - 1)
    return pnl_pts, exit_bar, exit_reason


def run_backtest_v3(
    df: pd.DataFrame,
    entries: List[Tuple[int, str, str, float, float, float, float, float, float]],
    initial_balance: float = 50_000.0,
    point_value: float = POINT_VALUE,
    spread_pts: float = SPREAD_PTS,
    slippage_pts: float = SLIPPAGE_PTS,
) -> BacktestResultV3:
    """
    entries: (bar_i, strategy, direction, entry, sl, tp1, tp2, trail_pts, risk_pct).
    Max 1 open trade; circuit breakers 2% daily, 6% weekly, 12% monthly.
    """
    cost_pts = spread_pts + slippage_pts
    if df is None or df.empty or "close" not in df.columns:
        eq = pd.Series([initial_balance])
        return BacktestResultV3(
            equity_curve=eq,
            trades=pd.DataFrame(),
            initial_balance=initial_balance,
            final_balance=initial_balance,
            metrics={},
            circuit_breakers_triggered=[],
        )
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    idx = df.index
    n = len(idx)
    balance = initial_balance
    equity = np.full(n, initial_balance, dtype=float)
    trades_list = []
    triggered = []
    daily_start = {}
    weekly_start = {}
    monthly_start = {}
    next_entry_idx = 0
    exit_bar_last = -1

    while next_entry_idx < len(entries):
        (bar_i, strat, direction, entry, sl, tp1, tp2, trail_pts, risk_pct) = entries[next_entry_idx]
        if bar_i <= exit_bar_last or bar_i >= n:
            next_entry_idx += 1
            continue
        sl_pts = abs(entry - sl)
        if sl_pts < 1e-6:
            next_entry_idx += 1
            continue
        risk_pct = min(2.0, max(0.5, risk_pct)) * 100.0
        risk_amount = balance * (risk_pct / 100.0)
        lots = risk_amount / (sl_pts * point_value) if (sl_pts * point_value) > 0 else 0
        if lots <= 0:
            next_entry_idx += 1
            continue

        try:
            entry_date = idx[bar_i].date()
        except Exception:
            entry_date = date(2000, 1, 1)
        if entry_date not in daily_start:
            daily_start[entry_date] = balance
        if balance - daily_start[entry_date] <= -initial_balance * (CIRCUIT_BREAKERS_V3["daily_loss_pct_stop"] / 100.0):
            triggered.append("daily_limit")
            break
        w = entry_date.isocalendar()[1]
        y = entry_date.year
        wk = (y, w)
        if wk not in weekly_start:
            weekly_start[wk] = balance
        if balance <= weekly_start[wk] * (1 - CIRCUIT_BREAKERS_V3["weekly_loss_pct_stop"] / 100.0):
            triggered.append("weekly_limit")
            break
        mon = (entry_date.year, entry_date.month)
        if mon not in monthly_start:
            monthly_start[mon] = balance
        if balance <= monthly_start[mon] * (1 - CIRCUIT_BREAKERS_V3["monthly_loss_pct_stop"] / 100.0):
            triggered.append("monthly_limit")
            break

        pnl_pts, exit_bar, exit_reason = _run_one_trade(
            high, low, close, idx, bar_i, direction, entry, sl, tp1, tp2, trail_pts, cost_pts
        )
        pnl = pnl_pts * lots * point_value
        balance += pnl
        exit_bar_last = exit_bar
        try:
            exit_time = idx[min(exit_bar, n - 1)]
        except Exception:
            exit_time = exit_bar
        trades_list.append({
            "entry_time": idx[bar_i],
            "exit_time": exit_time,
            "strategy": strat,
            "direction": direction,
            "entry": entry,
            "sl": sl,
            "pnl": pnl,
            "pnl_pts": pnl_pts,
            "result": "win" if pnl > 0 else "loss",
            "risk_pct": risk_pct,
            "exit_reason": exit_reason,
        })
        for i in range(bar_i, min(exit_bar + 1, n)):
            equity[i] = balance
        next_entry_idx += 1

    for i in range(1, n):
        if equity[i] == initial_balance:
            equity[i] = equity[i - 1]
    equity_curve = pd.Series(equity, index=idx)
    trades_df = pd.DataFrame(trades_list) if trades_list else pd.DataFrame()
    metrics = _compute_metrics_v3(trades_df, equity_curve, initial_balance, idx)
    return BacktestResultV3(
        equity_curve=equity_curve,
        trades=trades_df,
        initial_balance=initial_balance,
        final_balance=balance,
        metrics=metrics,
        circuit_breakers_triggered=triggered,
    )


def _compute_metrics_v3(
    trades: pd.DataFrame,
    equity: pd.Series,
    initial: float,
    idx: pd.DatetimeIndex,
) -> dict:
    if trades is None or trades.empty:
        days = max(1, (idx[-1] - idx[0]).days) if len(idx) > 1 else 1
        return {
            "signals_per_day": 0.0,
            "win_rate_pct": 0.0,
            "monthly_return_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "trade_count": 0,
            "total_return_pct": 0.0,
        }
    n_trades = len(trades)
    wins = (trades["pnl"] > 0).sum()
    win_rate = (wins / n_trades * 100.0) if n_trades else 0.0
    gross_wins = trades.loc[trades["pnl"] > 0, "pnl"].sum()
    gross_losses = abs(trades.loc[trades["pnl"] <= 0, "pnl"].sum())
    pf = (gross_wins / gross_losses) if gross_losses > 0 else (gross_wins if gross_wins > 0 else 0.0)
    total_return = (equity.iloc[-1] - initial) / initial * 100.0 if initial > 0 else 0.0
    run_days = max(1, (idx[-1] - idx[0]).days) if len(idx) > 1 else 1
    trading_days = run_days
    signals_per_day = n_trades / trading_days if trading_days else 0.0
    monthly_return = total_return * (30.0 / trading_days) if trading_days else 0.0
    cum = equity.values
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum) / np.where(peak > 0, peak, 1) * 100.0
    max_dd = float(np.nanmax(dd)) if len(dd) else 0.0
    return {
        "signals_per_day": round(signals_per_day, 4),
        "win_rate_pct": round(win_rate, 2),
        "monthly_return_pct": round(monthly_return, 2),
        "profit_factor": round(pf, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "trade_count": n_trades,
        "total_return_pct": round(total_return, 2),
    }
