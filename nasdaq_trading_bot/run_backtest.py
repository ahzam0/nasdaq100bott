"""
Run a single backtest with $50,000 initial balance.
Usage: python run_backtest.py [--asset QQQ] [--start 2018-01-01] [--end 2022-12-31]
       python run_backtest.py --live   (last 2 years up to today)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from backtest.metrics import count_targets_met
from data.pipeline import get_pipeline
from strategies import (
    TrendFollowingNasdaqStrategy,
    SmartMoneyNasdaqStrategy,
    BreakoutNasdaqStrategy,
    MultiTimeframeNasdaqStrategy,
    MomentumRiskAdjustedNasdaqStrategy,
)
from utils.config import TARGETS


INITIAL_BALANCE = 50_000.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", default="QQQ", help="Symbol to backtest")
    parser.add_argument("--start", default="2018-01-01", help="Start date")
    parser.add_argument("--end", default="2022-12-31", help="End date")
    parser.add_argument("--live", action="store_true", help="Use last 2 years up to today (current live data)")
    parser.add_argument(
        "--strategy",
        choices=["trend_following", "smart_money", "breakout", "multi_timeframe", "momentum_risk_adjusted"],
        default="trend_following",
    )
    args = parser.parse_args()

    if args.live:
        end_d = datetime.now()
        args.end = end_d.strftime("%Y-%m-%d")
        start_d = datetime(end_d.year - 2, end_d.month, end_d.day)
        args.start = start_d.strftime("%Y-%m-%d")
        print(f"Live data range: {args.start} -> {args.end}")

    # Load data
    df = get_pipeline(args.asset, args.start, args.end, interval="1d", with_qqq=True)
    if df is None or df.empty or len(df) < 50:
        print("Insufficient data; using synthetic series for demo.")
        np.random.seed(42)
        dates = pd.date_range(args.start, args.end, freq="B")
        close = 100 + np.cumsum(np.random.randn(len(dates)) * 0.8)
        df = pd.DataFrame({
            "open": np.roll(close, 1), "high": close + np.abs(np.random.randn(len(dates))),
            "low": close - np.abs(np.random.randn(len(dates))), "close": close,
            "volume": np.full(len(dates), 1_000_000),
        }, index=dates)
        df["open"].iloc[0] = 100

    if "close" not in df.columns:
        print("Error: no close prices.")
        return 1

    prices = df["close"]
    benchmark_returns = prices.pct_change().dropna()

    # Strategy signals (NASDAQ top proven strategies)
    strategy_map = {
        "trend_following": TrendFollowingNasdaqStrategy(ema_period=200),
        "smart_money": SmartMoneyNasdaqStrategy(lookback_bars=20, prefer_kill_zone=False),
        "breakout": BreakoutNasdaqStrategy(structure_lookback=20, retest_bars=5),
        "multi_timeframe": MultiTimeframeNasdaqStrategy(htf_ema=50, mtf_ema=21, ltf_ema=9),
        "momentum_risk_adjusted": MomentumRiskAdjustedNasdaqStrategy(trend_ema=50, momentum_period=20),
    }
    strat = strategy_map[args.strategy]
    signals = strat.generate_signals(df, args.asset)

    # Backtest with $50,000
    engine = BacktestEngine(initial_balance=INITIAL_BALANCE)
    res = engine.run(prices, signals, benchmark_returns=benchmark_returns)

    m = res.metrics
    if m is None:
        print("No metrics (empty backtest).")
        return 0

    # Report
    targets = TARGETS or {}
    targets_hit = count_targets_met(m, targets)
    print()
    print("=" * 56)
    print("  BACKTEST REPORT — $50,000 INITIAL BALANCE")
    print("=" * 56)
    print(f"  Asset:        {args.asset}")
    print(f"  Strategy:     {args.strategy}")
    print(f"  Period:       {args.start}  to  {args.end}")
    print("-" * 56)
    print(f"  Initial:      ${res.initial_balance:,.2f}")
    print(f"  Final:        ${res.final_balance:,.2f}")
    print(f"  Total return: {m.total_return_pct:.2f}%")
    print(f"  CAGR:         {m.cagr_pct:.1f}%")
    print("-" * 56)
    print(f"  Sharpe:       {m.sharpe_ratio:.2f}")
    print(f"  Sortino:      {m.sortino_ratio:.2f}")
    print(f"  Calmar:       {m.calmar_ratio:.2f}")
    print(f"  Max drawdown: {m.max_drawdown_pct:.1f}%")
    print(f"  Ann. vol:     {m.annual_volatility_pct:.1f}%")
    print("-" * 56)
    print(f"  Trades:       {m.total_trades}  (W: {m.winners} / L: {m.losers})")
    print(f"  Win rate:     {m.win_rate_pct:.1f}%")
    print(f"  Profit factor:{m.profit_factor:.2f}")
    print(f"  Expectancy:   ${m.expectancy_per_r:.2f} per $1 risked")
    print(f"  Max consec L: {m.max_consecutive_losses}")
    print("-" * 56)
    print(f"  Targets hit:  {targets_hit}/10")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
