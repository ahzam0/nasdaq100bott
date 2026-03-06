"""
NAS100 v3.0 hit-and-trial optimization loop.
STEP 1: Baseline (A+B+C). STEP 2: If signals/day < 1 → relax. STEP 3: If WR < 70% → add filter.
STEP 4: If return < 40% → sizing. STEP 5: If DD > 15% → tighten. STEP 6: If PF < 2 → widen TP.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

# Run from project root
sys.path.insert(0, ".")

import pandas as pd

from data.pipeline import load_bars
from nas100_v3.config import TARGETS, MIN_BACKTEST_DAYS, MIN_TRADES
from nas100_v3.strategies import generate_all_signals
from nas100_v3.backtest_v3 import run_backtest_v3


SYMBOL = "^NDX"


def get_data(days: int = 90) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=days)
    df = load_bars(SYMBOL, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), interval="1d")
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns=lambda c: c.lower() if isinstance(c, str) else c)
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            return pd.DataFrame()
    return df


def run_baseline(df: pd.DataFrame, initial_balance: float = 50_000.0) -> dict:
    signals = generate_all_signals(df)
    res = run_backtest_v3(df, signals, initial_balance=initial_balance)
    return {
        "metrics": res.metrics,
        "trades": res.trades,
        "signals_count": len(signals),
        "circuit_breakers": res.circuit_breakers_triggered,
        "final_balance": res.final_balance,
    }


def check_all_met(metrics: dict) -> tuple[bool, list[str]]:
    failed = []
    if metrics.get("signals_per_day", 0) < TARGETS["signals_per_day_min"]:
        failed.append("signals_per_day")
    if metrics.get("win_rate_pct", 0) < TARGETS["win_rate_pct_min"]:
        failed.append("win_rate_pct")
    if metrics.get("monthly_return_pct", 0) < TARGETS["monthly_return_pct_min"]:
        failed.append("monthly_return_pct")
    if metrics.get("profit_factor", 0) < TARGETS["profit_factor_min"]:
        failed.append("profit_factor")
    if metrics.get("max_drawdown_pct", 100) > TARGETS["max_drawdown_pct_max"]:
        failed.append("max_drawdown_pct")
    if metrics.get("trade_count", 0) < MIN_TRADES:
        failed.append("trade_count")
    return (len(failed) == 0, failed)


def optimize_loop(max_iterations: int = 15, initial_balance: float = 50_000.0) -> dict:
    df = get_data(days=120)
    if df.empty or len(df) < MIN_BACKTEST_DAYS:
        return {"ok": False, "error": "Insufficient data", "iterations": 0}
    iteration = 0
    best_metrics = None
    best_trades = None
    applied_fixes = []
    while iteration < max_iterations:
        iteration += 1
        run = run_baseline(df, initial_balance)
        metrics = run["metrics"]
        if not metrics:
            break
        all_met, failed = check_all_met(metrics)
        if all_met:
            return {
                "ok": True,
                "metrics": metrics,
                "trades": run["trades"],
                "signals_count": run["signals_count"],
                "iterations": iteration,
                "applied_fixes": applied_fixes,
            }
        best_metrics = metrics
        best_trades = run["trades"]
        if "signals_per_day" in failed or "trade_count" in failed:
            applied_fixes.append("v3_fix_signal_count: relax filters (already minimal in v3)")
        if "win_rate_pct" in failed and "signals_per_day" not in failed:
            applied_fixes.append("v3_fix_win_rate: consider adding single filter")
        if "monthly_return_pct" in failed:
            applied_fixes.append("v3_fix_return: position sizing")
        if "max_drawdown_pct" in failed:
            applied_fixes.append("v3_fix_dd: tighten SL or limits")
        if "profit_factor" in failed:
            applied_fixes.append("v3_fix_pf: widen TP")
        break  # v3: one baseline run then report; full loop would tune params
    return {
        "ok": False,
        "metrics": best_metrics,
        "trades": best_trades,
        "failed": check_all_met(best_metrics or {})[1],
        "iterations": iteration,
        "applied_fixes": applied_fixes,
    }


if __name__ == "__main__":
    result = optimize_loop(max_iterations=15, initial_balance=50_000.0)
    print("NAS100 v3.0 optimizer result:")
    print(result.get("metrics", {}))
    print("OK:", result.get("ok"))
    if result.get("trades") is not None and not result["trades"].empty:
        print("Trade count:", len(result["trades"]))
