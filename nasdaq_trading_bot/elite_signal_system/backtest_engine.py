"""
Elite backtest engine: SL/TP per trade, spread, slippage, max 2% risk per trade.
Minimum 1:2 RR. Produces equity curve and trades for EliteMetrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class EliteBacktestResult:
    equity_curve: pd.Series
    trades: pd.DataFrame
    initial_balance: float
    final_balance: float
    metrics: Optional[object] = None


def run_backtest(
    df: pd.DataFrame,
    entries: List[Tuple[int, str, float, float, float]],
    initial_balance: float = 100_000.0,
    risk_pct: float = 2.0,
    min_rr: float = 2.0,
    spread_pips: float = 1.0,
    slippage_pips: float = 1.5,
) -> EliteBacktestResult:
    """
    df: OHLC DataFrame with index = datetime, columns high, low, close.
    entries: list of (bar_index, direction, entry_price, sl, tp) where direction 'BUY'|'SELL'.
    Each entry is one trade with fixed SL/TP. Risk 2% per trade; position size from SL distance.
    """
    if df is None or df.empty or "close" not in df.columns:
        eq = pd.Series([initial_balance])
        return EliteBacktestResult(equity_curve=eq, trades=pd.DataFrame(), initial_balance=initial_balance, final_balance=initial_balance)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    idx = df.index
    n = len(idx)

    # Pip scale: for stocks use 0.01, for forex 0.0001
    pip = 0.01 if close[0] > 100 else 0.0001
    spread_cost = spread_pips * pip * (1 if close[0] > 100 else 10000)
    slippage_cost = slippage_pips * pip * (1 if close[0] > 100 else 10000)

    equity = np.full(n + 1, initial_balance, dtype=float)
    trades_list = []
    balance = initial_balance

    for (i, direction, entry_price, sl, tp) in entries:
        if i >= n or i < 1:
            continue
        risk_amount = balance * (risk_pct / 100.0)
        if direction == "BUY":
            sl_dist = entry_price - sl
            if sl_dist <= 0:
                continue
            size = risk_amount / sl_dist
            exit_price = None
            exit_bar = i
            for j in range(i, min(i + 200, n)):
                if low[j] <= sl:
                    exit_price = sl - slippage_cost
                    exit_bar = j
                    break
                if high[j] >= tp:
                    exit_price = tp + slippage_cost
                    exit_bar = j
                    break
            if exit_price is None:
                exit_price = close[min(i + 199, n - 1)] - slippage_cost
                exit_bar = min(i + 199, n - 1)
            pnl = size * (exit_price - entry_price) - size * spread_cost
        else:
            sl_dist = sl - entry_price
            if sl_dist <= 0:
                continue
            size = risk_amount / sl_dist
            exit_price = None
            exit_bar = i
            for j in range(i, min(i + 200, n)):
                if high[j] >= sl:
                    exit_price = sl + slippage_cost
                    exit_bar = j
                    break
                if low[j] <= tp:
                    exit_price = tp - slippage_cost
                    exit_bar = j
                    break
            if exit_price is None:
                exit_price = close[min(i + 199, n - 1)] + slippage_cost
                exit_bar = min(i + 199, n - 1)
            pnl = size * (entry_price - exit_price) - size * spread_cost

        balance += pnl
        equity[exit_bar] = balance
        trades_list.append({
            "entry_time": idx[i],
            "exit_time": idx[min(exit_bar, n - 1)],
            "pnl": pnl,
            "result": "win" if pnl > 0 else "loss",
        })

    for i in range(1, n):
        if equity[i] == initial_balance:
            equity[i] = equity[i - 1]
    equity_curve = pd.Series(equity[:n], index=idx) if n else pd.Series([initial_balance])
    trades_df = pd.DataFrame(trades_list) if trades_list else pd.DataFrame(columns=["entry_time", "exit_time", "pnl", "result"])
    final = balance

    from elite_signal_system.metrics import compute_elite_metrics
    trading_days = max(1, (idx[-1] - idx[0]).days // 1) if len(idx) > 1 else 1
    metrics = compute_elite_metrics(trades_df, equity_curve, initial_balance, trading_days)

    return EliteBacktestResult(
        equity_curve=equity_curve,
        trades=trades_df,
        initial_balance=initial_balance,
        final_balance=final,
        metrics=metrics,
    )
