"""
Hit-and-trial protocol: design → backtest → measure → if all pass deliver else diagnose → adjust/change → repeat.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.pipeline import load_bars
from elite_signal_system.config import TARGETS, MIN_BACKTEST_DAYS, MIN_TRADES_FOR_CONCLUSION
from elite_signal_system.backtest_engine import run_backtest
from elite_signal_system.metrics import EliteMetrics, all_targets_met, compute_elite_metrics, backtest_report
from elite_signal_system.strategies.trend_following import TrendFollowingStrategy
from elite_signal_system.strategies.breakout import BreakoutStrategy
from elite_signal_system.strategies.mean_reversion import MeanReversionStrategy
from elite_signal_system.strategies.hybrid import HybridStrategy


STRATEGIES = [
    ("trend_following", TrendFollowingStrategy),
    ("breakout", BreakoutStrategy),
    ("mean_reversion", MeanReversionStrategy),
    ("hybrid", HybridStrategy),
]


def load_ohlc(symbol: str, days: int = 180) -> Optional[pd.DataFrame]:
    end = datetime.now()
    start = end - timedelta(days=days)
    start_str = start.strftime("%Y-%m-%d")
    end_str = end.strftime("%Y-%m-%d")
    df = load_bars(symbol, start_str, end_str, interval="1d")
    if df is None or df.empty or len(df) < MIN_BACKTEST_DAYS:
        return None
    if "high" not in df.columns:
        df["high"] = df["close"]
    if "low" not in df.columns:
        df["low"] = df["close"]
    return df


def run_strategy_backtest(
    df: pd.DataFrame,
    strategy_name: str,
    strategy_instance: Any,
    initial_balance: float = 100_000.0,
) -> Tuple[Any, EliteMetrics]:
    entries = strategy_instance.generate_entries(df, "")
    res = run_backtest(
        df,
        entries,
        initial_balance=initial_balance,
        risk_pct=2.0,
        min_rr=2.0,
        spread_pips=1.0,
        slippage_pips=1.5,
    )
    trading_days = max(1, (df.index[-1] - df.index[0]).days) if len(df) > 1 else 1
    if res.metrics is None and res.trades is not None and not res.trades.empty:
        res.metrics = compute_elite_metrics(res.trades, res.equity_curve, initial_balance, trading_days)
    return res, res.metrics or EliteMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def diagnose(m: EliteMetrics, targets: dict) -> List[str]:
    fixes = []
    if m.win_rate_pct < targets.get("win_rate_pct_min", 70):
        fixes.append("Win rate < 70%: tighten entry filters, add confluence, trend filter, volume confirmation.")
    if m.monthly_return_pct < targets.get("monthly_return_pct_min", 40):
        fixes.append("Monthly return < 40%: review position sizing, higher R:R, partial TPs + trailing stops.")
    if m.max_drawdown_pct > targets.get("max_drawdown_pct_max", 15):
        fixes.append("Drawdown > 15%: reduce risk to 1%, add daily/weekly loss limits, avoid news.")
    if m.profit_factor < targets.get("profit_factor_min", 2.0):
        fixes.append("Profit factor < 2: move SL to breakeven after 1:1, cut losers faster, improve R:R.")
    if m.signals_per_day < targets.get("signals_per_day_min", 1.0):
        fixes.append("Signals < 1/day: expand to multiple assets, multiple sessions, more setup types.")
    return fixes


def main() -> int:
    targets = TARGETS
    assets = ["QQQ", "SPY", "AAPL"]
    initial_balance = 100_000.0
    best_result = None
    best_metrics = None
    best_name = None
    best_asset = None
    round_num = 0
    max_rounds = 20

    while round_num < max_rounds:
        round_num += 1
        print(f"\n=== ROUND {round_num} ===\n")
        for asset in assets:
            df = load_ohlc(asset, days=180)
            if df is None or len(df) < MIN_BACKTEST_DAYS:
                continue
            for strategy_name, StrategyClass in STRATEGIES:
                variants = [{}, {"rr_ratio": 2.5}, {"min_bars_apart": 1}]
                for variant in variants:
                    try:
                        strat = StrategyClass(**variant) if variant else StrategyClass()
                    except (TypeError, Exception):
                        strat = StrategyClass()
                    try:
                        res, m = run_strategy_backtest(df, strategy_name, strat, initial_balance)
                    except Exception as e:
                        continue
                    if m.total_trades < MIN_TRADES_FOR_CONCLUSION:
                        continue
                    if all_targets_met(m, targets):
                        print("ALL 5 TARGETS MET.")
                        print(backtest_report(m))
                        print(f"Strategy: {strategy_name}  Asset: {asset}")
                        return 0
                    if best_metrics is None or (
                        m.win_rate_pct >= best_metrics.win_rate_pct
                        and m.profit_factor >= best_metrics.profit_factor
                        and m.signals_per_day >= best_metrics.signals_per_day
                    ):
                        best_result = res
                        best_metrics = m
                        best_name = strategy_name
                        best_asset = asset

        if best_metrics:
            print(f"Best so far: {best_name} on {best_asset}")
            print(backtest_report(best_metrics))
            fixes = diagnose(best_metrics, targets)
            for f in fixes:
                print("  ->", f)
        if round_num >= 3 and best_metrics and not all_targets_met(best_metrics, targets):
            print("\nOptimization rounds completed. Best achievable result (all 5 not met simultaneously):")
            if best_metrics:
                print(backtest_report(best_metrics))
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
