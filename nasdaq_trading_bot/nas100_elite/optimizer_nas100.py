"""
Hit-and-trial loop — NAS100 specific.
Round 1: ORB, Round 2: OB, Round 3: Key Level, Round 4: Hybrid. Round 5+: optimize risk.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.pipeline import load_bars
from nas100_elite.config import MIN_BACKTEST_DAYS, MIN_TRADES_FOR_SUCCESS, TARGETS
from nas100_elite.backtest_nas100 import run_nas100_backtest
from nas100_elite.metrics_nas100 import all_targets_met, NAS100Metrics
from nas100_elite.strategies import ORBStrategy, OrderBlockStrategy, KeyLevelStrategy, HybridNAS100Strategy


# Use ^NDX (NASDAQ-100 index) as proxy for NAS100 points
SYMBOL = "^NDX"


def load_nas100(days: int = 180) -> pd.DataFrame | None:
    end = datetime.now()
    start = end - timedelta(days=days)
    df = load_bars(SYMBOL, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), interval="1d")
    if df is None or df.empty or len(df) < MIN_BACKTEST_DAYS:
        return None
    if "high" not in df.columns:
        df["high"] = df["close"]
    if "low" not in df.columns:
        df["low"] = df["close"]
    if "volume" not in df.columns:
        df["volume"] = 1_000_000
    return df


def main() -> int:
    df = load_nas100(180)
    if df is None:
        print("No NAS100/NDX data.")
        return 1
    trading_days = max(1, (df.index[-1] - df.index[0]).days)
    initial_balance = 10_000.0
    best_metrics = None
    best_name = None
    best_result = None

    strategies = [
        ("ORB", ORBStrategy(atr_min_points=15, min_bars_apart=1)),
        ("OrderBlock", OrderBlockStrategy(min_bars_apart=1)),
        ("KeyLevel", KeyLevelStrategy(min_bars_apart=1)),
        ("Hybrid", HybridNAS100Strategy()),
    ]

    for round_name, strat in strategies:
        entries = strat.generate_entries(df)
        if len(entries) < MIN_TRADES_FOR_SUCCESS:
            continue
        res = run_nas100_backtest(df, entries, initial_balance=initial_balance)
        m = res.metrics
        if m is None:
            continue
        if all_targets_met(m):
            print("ALL 5 TARGETS MET.")
            print(f"Strategy: {round_name}")
            print(f"  Win rate: {m.win_rate_pct:.1f}%  Monthly: {m.monthly_return_pct:.1f}%  PF: {m.profit_factor:.2f}  DD: {m.max_drawdown_pct:.1f}%  Signals/day: {m.signals_per_day:.2f}")
            return 0
        if best_metrics is None or m.win_rate_pct >= best_metrics.win_rate_pct:
            best_metrics = m
            best_name = round_name
            best_result = res

    if best_metrics:
        print("Best result (all 5 not met simultaneously):")
        print(f"  Strategy: {best_name}")
        print(f"  Win rate: {best_metrics.win_rate_pct:.1f}%  [target >= {TARGETS['win_rate_pct_min']}%]")
        print(f"  Monthly return: {best_metrics.monthly_return_pct:.1f}%  [target >= {TARGETS['monthly_return_pct_min']}%]")
        print(f"  Profit factor: {best_metrics.profit_factor:.2f}  [target >= {TARGETS['profit_factor_min']}]")
        print(f"  Max drawdown: {best_metrics.max_drawdown_pct:.1f}%  [target <= {TARGETS['max_drawdown_pct_max']}%]")
        print(f"  Signals/day: {best_metrics.signals_per_day:.2f}  [target >= {TARGETS['signals_per_day_min']}]")
        print(f"  Trades: {best_metrics.total_trades}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
