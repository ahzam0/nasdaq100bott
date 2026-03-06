"""
Hit and Trail backtest: take-profit (hit) + trailing-stop (trail).
Targets: 40% min return in one month, 70% min win rate, good profit factor,
         lowest drawdown, minimum 1 trade per day.
Usage: python run_hit_and_trail.py [--asset QQQ] [--start ...] [--end ...] [--live]
       --take-profit 0.02 --trail 0.01
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
from strategies import TrendFollowingNasdaqStrategy
from data.pipeline import get_pipeline


INITIAL_BALANCE = 50_000.0

# Your targets
TARGET_MONTHLY_RETURN_PCT = 40.0
TARGET_WIN_RATE_PCT = 70.0
TARGET_PROFIT_FACTOR = 2.0
TARGET_MIN_TRADES_PER_DAY = 1.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", default="QQQ")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--live", action="store_true", help="Last 2 years to today")
    parser.add_argument("--take-profit", type=float, default=0.02, help="Take-profit (hit) e.g. 0.02 = 2%%")
    parser.add_argument("--trail", type=float, default=0.01, help="Trailing stop e.g. 0.01 = 1%%")
    parser.add_argument("--one-month", action="store_true", help="Run on single month only (for 40%%/month target)")
    args = parser.parse_args()

    if args.live:
        end_d = datetime.now()
        args.end = end_d.strftime("%Y-%m-%d")
        start_d = datetime(end_d.year - 2, end_d.month, end_d.day)
        args.start = start_d.strftime("%Y-%m-%d")
        print(f"Live range: {args.start} to {args.end}")

    if args.one_month:
        args.end = (pd.Timestamp(args.start) + pd.DateOffset(months=1)).strftime("%Y-%m-%d")
        print(f"One-month window: {args.start} to {args.end}")

    df = get_pipeline(args.asset, args.start, args.end, interval="1d", with_qqq=True)
    if df is None or df.empty or len(df) < 50:
        print("Insufficient data; using synthetic OHLC.")
        np.random.seed(42)
        dates = pd.date_range(args.start, args.end, freq="B")
        close = 100 + np.cumsum(np.random.randn(len(dates)) * 0.8)
        df = pd.DataFrame({
            "open": np.roll(close, 1),
            "high": close + np.abs(np.random.randn(len(dates))),
            "low": close - np.abs(np.random.randn(len(dates))),
            "close": close,
            "volume": np.full(len(dates), 1_000_000),
        }, index=dates)
        df["open"].iloc[0] = 100

    if "high" not in df.columns:
        df["high"] = df["close"]
    if "low" not in df.columns:
        df["low"] = df["close"]

    strat = TrendFollowingNasdaqStrategy(ema_period=200)
    signals = strat.generate_signals(df, args.asset)

    engine = BacktestEngine(initial_balance=INITIAL_BALANCE)
    res = engine.run_hit_and_trail(
        df,
        signals,
        take_profit_pct=args.take_profit,
        trailing_stop_pct=args.trail,
        eod_exit=getattr(args, "eod_exit", True),
    )

    m = res.metrics
    if m is None:
        print("No metrics.")
        return 0

    trades_df = res.trades
    n_trades = len(trades_df)
    trading_days = max(1, len(df))
    trades_per_day = n_trades / trading_days if trading_days else 0

    months = trading_days / 21.0 if trading_days else 0
    total_ret_pct = m.total_return_pct
    monthly_ret_pct = ((1 + total_ret_pct / 100) ** (1 / months) - 1) * 100 if months > 0 else total_ret_pct

    hit_count = sum(1 for _, r in trades_df.iterrows() if r.get("exit_reason") == "hit")
    trail_count = sum(1 for _, r in trades_df.iterrows() if r.get("exit_reason") == "trail")
    signal_count = sum(1 for _, r in trades_df.iterrows() if r.get("exit_reason") == "signal")

    ok_monthly = monthly_ret_pct >= TARGET_MONTHLY_RETURN_PCT
    ok_wr = m.win_rate_pct >= TARGET_WIN_RATE_PCT
    ok_pf = m.profit_factor >= TARGET_PROFIT_FACTOR
    ok_tpd = trades_per_day >= TARGET_MIN_TRADES_PER_DAY

    print()
    print("=" * 60)
    print("  HIT AND TRAIL BACKTEST")
    print("=" * 60)
    print(f"  Asset:           {args.asset}")
    print(f"  Period:          {args.start}  to  {args.end}")
    print(f"  Take-profit:     {args.take_profit * 100:.1f}%%  |  Trailing stop: {args.trail * 100:.1f}%%")
    print("-" * 60)
    print(f"  Initial:         ${res.initial_balance:,.2f}")
    print(f"  Final:           ${res.final_balance:,.2f}")
    print(f"  Total return:    {total_ret_pct:.2f}%%")
    print(f"  Monthly return:  {monthly_ret_pct:.1f}%%  [target >= {TARGET_MONTHLY_RETURN_PCT}%%]  {'OK' if ok_monthly else 'MISS'}")
    print("-" * 60)
    print(f"  Win rate:        {m.win_rate_pct:.1f}%%  [target >= {TARGET_WIN_RATE_PCT}%%]  {'OK' if ok_wr else 'MISS'}")
    print(f"  Profit factor:   {m.profit_factor:.2f}  [target >= {TARGET_PROFIT_FACTOR}]  {'OK' if ok_pf else 'MISS'}")
    print(f"  Max drawdown:    {m.max_drawdown_pct:.1f}%%  (lowest is better)")
    print(f"  Trades/day:      {trades_per_day:.2f}  [target >= {TARGET_MIN_TRADES_PER_DAY}]  {'OK' if ok_tpd else 'MISS'}")
    print("-" * 60)
    print(f"  Trades:          {n_trades}  (W: {m.winners} / L: {m.losers})")
    print(f"  Exits:           hit={hit_count}  trail={trail_count}  signal={signal_count}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
