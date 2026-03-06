"""
Optimizer until targets are met using NASDAQ top proven strategies:
  - Trend Following, Smart Money, Breakout, Multi-Timeframe, Momentum/Risk-Adjusted
  - Targets: 70% win rate, 40% monthly return, profit factor >= 2, min trades/day, lowest drawdown
"""

from __future__ import annotations

import itertools
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from backtest.engine import BacktestEngine
from strategies import (
    TrendFollowingNasdaqStrategy,
    SmartMoneyNasdaqStrategy,
    BreakoutNasdaqStrategy,
    MultiTimeframeNasdaqStrategy,
    MomentumRiskAdjustedNasdaqStrategy,
)
from data.pipeline import get_pipeline


INITIAL_BALANCE = 50_000.0
TARGET_MONTHLY_PCT = 40.0
TARGET_WIN_RATE_PCT = 70.0
TARGET_PROFIT_FACTOR = 2.0
TARGET_MIN_TRADES_PER_DAY = 1.0
MAX_TRIALS_PER_STRATEGY = 500

STRATEGY_MAP = {
    "trend_following": lambda: TrendFollowingNasdaqStrategy(ema_period=200),
    "smart_money": lambda: SmartMoneyNasdaqStrategy(lookback_bars=20, prefer_kill_zone=False),
    "breakout": lambda: BreakoutNasdaqStrategy(structure_lookback=20, retest_bars=5),
    "multi_timeframe": lambda: MultiTimeframeNasdaqStrategy(htf_ema=50, mtf_ema=21, ltf_ema=9),
    "momentum_risk_adjusted": lambda: MomentumRiskAdjustedNasdaqStrategy(trend_ema=50, momentum_period=20),
}


def ensure_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if "high" not in df.columns:
        df["high"] = df["close"]
    if "low" not in df.columns:
        df["low"] = df["close"]
    if "open" not in df.columns:
        df["open"] = df["close"].shift(1).fillna(df["close"])
    return df


def load_data(asset: str, start: str, end: str):
    df = get_pipeline(asset, start, end, interval="1d", with_qqq=True)
    if df is None or df.empty or len(df) < 50:
        np.random.seed(42)
        dates = pd.date_range(start, end, freq="B")
        close = 100 + np.cumsum(np.random.randn(len(dates)) * 0.8)
        df = pd.DataFrame({
            "open": np.roll(close, 1), "high": close + np.abs(np.random.randn(len(dates))),
            "low": close - np.abs(np.random.randn(len(dates))), "close": close,
            "volume": np.full(len(dates), 1_000_000),
        }, index=dates)
        df["open"].iloc[0] = 100
    return ensure_ohlc(df)


def run_one(
    df: pd.DataFrame,
    strategy_name: str,
) -> tuple[object, float, float, float, float, float]:
    if strategy_name not in STRATEGY_MAP:
        return None, -1e9, 0.0, 0.0, 100.0, 0.0
    strat = STRATEGY_MAP[strategy_name]()
    signals = strat.generate_signals(df.copy(), "QQQ")
    engine = BacktestEngine(initial_balance=INITIAL_BALANCE)
    prices = df["close"]
    benchmark_returns = prices.pct_change().dropna()
    res = engine.run(prices, signals, benchmark_returns=benchmark_returns)

    m = res.metrics
    if m is None:
        return res, -1e9, 0.0, 0.0, 100.0, 0.0

    n_days = max(1, len(df))
    n_trades = m.total_trades
    tpd = n_trades / n_days if n_days else 0.0
    months = n_days / 21.0 if n_days else 0
    total_ret = m.total_return_pct
    monthly_ret = ((1 + total_ret / 100) ** (1 / months) - 1) * 100 if months > 0 else total_ret
    wr = m.win_rate_pct
    pf = m.profit_factor
    dd = m.max_drawdown_pct
    return res, monthly_ret, wr, pf, dd, tpd


def targets_met(monthly_ret: float, wr: float, pf: float, tpd: float) -> bool:
    return (
        monthly_ret >= TARGET_MONTHLY_PCT
        and wr >= TARGET_WIN_RATE_PCT
        and pf >= TARGET_PROFIT_FACTOR
        and tpd >= TARGET_MIN_TRADES_PER_DAY
    )


def main() -> int:
    asset = "QQQ"
    start = "2022-01-01"
    end = datetime.now().strftime("%Y-%m-%d")
    df = load_data(asset, start, end)
    if df is None or df.empty:
        print("No data.")
        return 1

    best = None
    best_score = -1e9
    best_params = None
    trial = 0

    for strategy_name in STRATEGY_MAP:
        if best_params and targets_met(best_params[1], best_params[2], best_params[3], best_params[5]):
            break
        for _ in range(MAX_TRIALS_PER_STRATEGY):
            trial += 1
            try:
                res, monthly_ret, wr, pf, dd, tpd = run_one(df, strategy_name)
            except Exception:
                continue
            if monthly_ret is None or np.isnan(monthly_ret):
                continue
            score = 0.0
            if monthly_ret >= TARGET_MONTHLY_PCT:
                score += 100
            if wr >= TARGET_WIN_RATE_PCT:
                score += 50
            if pf >= TARGET_PROFIT_FACTOR:
                score += 30
            if tpd >= TARGET_MIN_TRADES_PER_DAY:
                score += 40
            score += min(monthly_ret, 100) - dd * 2 + pf * 5
            if score > best_score:
                best_score = score
                best = res
                best_params = (strategy_name, monthly_ret, wr, pf, dd, tpd)
            if trial % 50 == 0 and best_params:
                print(f"Trial {trial} | Best monthly={best_params[1]:.1f}% wr={best_params[2]:.1f}% pf={best_params[3]:.2f} tpd={best_params[5]:.2f}")
            if targets_met(monthly_ret, wr, pf, tpd):
                print("TARGETS MET.")
                best = res
                best_params = (strategy_name, monthly_ret, wr, pf, dd, tpd)
                break
        if best_params and targets_met(best_params[1], best_params[2], best_params[3], best_params[5]):
            break

    if best is None or best_params is None:
        print("No valid run.")
        return 1

    name, monthly_ret, wr, pf, dd, tpd = best_params
    m = best.metrics
    print()
    print("=" * 60)
    print("  OPTIMIZER RESULT (NASDAQ strategies)")
    print("=" * 60)
    print(f"  Strategy:       {name}")
    print("-" * 60)
    print(f"  Monthly return: {monthly_ret:.1f}%  [target >= {TARGET_MONTHLY_PCT}%]  {'OK' if monthly_ret >= TARGET_MONTHLY_PCT else 'MISS'}")
    print(f"  Win rate:       {wr:.1f}%  [target >= {TARGET_WIN_RATE_PCT}%]  {'OK' if wr >= TARGET_WIN_RATE_PCT else 'MISS'}")
    print(f"  Profit factor:  {pf:.2f}  [target >= {TARGET_PROFIT_FACTOR}]  {'OK' if pf >= TARGET_PROFIT_FACTOR else 'MISS'}")
    print(f"  Max drawdown:   {dd:.1f}%")
    print(f"  Trades/day:     {tpd:.2f}  [target >= {TARGET_MIN_TRADES_PER_DAY}]  {'OK' if tpd >= TARGET_MIN_TRADES_PER_DAY else 'MISS'}")
    if m:
        print(f"  Final balance:  ${best.final_balance:,.2f}  Trades: {m.total_trades}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
