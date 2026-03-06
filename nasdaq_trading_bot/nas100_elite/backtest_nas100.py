"""
NAS100 backtest: point-based P&L, 2% risk (or by confluence), SL/TP in points, circuit breakers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from nas100_elite.config import (
    CIRCUIT_BREAKERS,
    POINT_VALUE_PER_LOT,
    TARGETS,
)
from nas100_elite.sizing import position_size_lots, validate_sl_points


@dataclass
class NAS100BacktestResult:
    equity_curve: pd.Series
    trades: pd.DataFrame
    initial_balance: float
    final_balance: float
    metrics: Optional[object] = None
    circuit_breakers_triggered: List[str] = None


def run_nas100_backtest(
    df: pd.DataFrame,
    entries: List[Tuple[int, str, float, float, float, float, float, float, str, int]],
    initial_balance: float = 10_000.0,
    point_value: float = POINT_VALUE_PER_LOT,
) -> NAS100BacktestResult:
    """
    entries: (bar_i, direction, entry, sl, tp1, tp2, trail_pts, risk_pct, setup_type, confluence).
    P&L in points * lots * point_value. Apply daily/weekly/monthly loss limits.
    """
    if df is None or df.empty or "close" not in df.columns:
        eq = pd.Series([initial_balance])
        return NAS100BacktestResult(equity_curve=eq, trades=pd.DataFrame(), initial_balance=initial_balance, final_balance=initial_balance, circuit_breakers_triggered=[])
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    idx = df.index
    n = len(idx)
    equity = np.full(n, initial_balance, dtype=float)
    trades_list = []
    balance = initial_balance
    last_exit_date = None
    consec_losses = 0
    triggered = []

    for (i, direction, entry_price, sl, tp1, tp2, trail_pts, risk_pct, setup_type, conf) in entries:
        if i >= n or i < 1:
            continue
        sl_pts = abs(entry_price - sl)
        if not validate_sl_points(sl_pts):
            continue
        risk_pct = min(2.0, max(1.0, risk_pct))
        lots = position_size_lots(balance, risk_pct, sl_pts, point_value)
        if lots <= 0:
            continue
        exit_price = None
        exit_bar = i
        for j in range(i, min(i + 100, n)):
            if direction == "BUY":
                if low[j] <= sl:
                    exit_price = sl
                    exit_bar = j
                    break
                if high[j] >= tp1:
                    exit_price = tp1
                    exit_bar = j
                    break
                if high[j] >= tp2:
                    exit_price = tp2
                    exit_bar = j
                    break
            else:
                if high[j] >= sl:
                    exit_price = sl
                    exit_bar = j
                    break
                if low[j] <= tp1:
                    exit_price = tp1
                    exit_bar = j
                    break
                if low[j] <= tp2:
                    exit_price = tp2
                    exit_bar = j
                    break
        if exit_price is None:
            exit_price = close[min(i + 99, n - 1)]
            exit_bar = min(i + 99, n - 1)
        pts = (exit_price - entry_price) if direction == "BUY" else (entry_price - exit_price)
        pnl = pts * lots * point_value
        try:
            exit_date = idx[exit_bar].date()
        except Exception:
            exit_date = exit_bar
        if exit_date != last_exit_date:
            daily_start = balance
        balance += pnl
        equity[exit_bar] = balance
        last_exit_date = exit_date
        won = pnl > 0
        if not won:
            consec_losses += 1
        else:
            consec_losses = 0
        trades_list.append({
            "entry_time": idx[i],
            "exit_time": idx[min(exit_bar, n - 1)],
            "pnl": pnl,
            "result": "win" if won else "loss",
            "setup_type": setup_type,
            "confluence": conf,
        })
        daily_loss_pct = (daily_start - balance) / daily_start * 100 if daily_start > 0 else 0
        if daily_loss_pct >= CIRCUIT_BREAKERS["daily_loss_pct_max"]:
            triggered.append("daily_limit")
            break
        if consec_losses >= CIRCUIT_BREAKERS["consecutive_losses_stop_week"]:
            triggered.append("consecutive_losses_week")
            break

    for i in range(1, n):
        if equity[i] == initial_balance:
            equity[i] = equity[i - 1]
    equity_curve = pd.Series(equity, index=idx)
    trades_df = pd.DataFrame(trades_list) if trades_list else pd.DataFrame(columns=["entry_time", "exit_time", "pnl", "result", "setup_type", "confluence"])
    trading_days = max(1, (idx[-1] - idx[0]).days) if len(idx) > 1 else 1
    from nas100_elite.metrics_nas100 import compute_nas100_metrics
    metrics = compute_nas100_metrics(trades_df, equity_curve, initial_balance, trading_days)
    return NAS100BacktestResult(
        equity_curve=equity_curve,
        trades=trades_df,
        initial_balance=initial_balance,
        final_balance=balance,
        metrics=metrics,
        circuit_breakers_triggered=triggered,
    )
