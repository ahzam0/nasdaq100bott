"""
Run NAS100 Signal System v3.0: load ^NDX, generate A+B+C signals, backtest, print result.
"""

from __future__ import annotations

import os
import sys

# Run from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from data.pipeline import load_bars
from nas100_v3.config import TARGETS, MIN_BACKTEST_DAYS, MIN_TRADES
from nas100_v3.strategies import generate_all_signals
from nas100_v3.backtest_v3 import run_backtest_v3


SYMBOL = "^NDX"
INITIAL_BALANCE = 50_000.0


def main():
    end = datetime.now()
    start = end - timedelta(days=120)
    df = load_bars(SYMBOL, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), interval="1d")
    if df is None or df.empty:
        print("No data for", SYMBOL)
        return
    df = df.rename(columns=lambda c: c.lower() if isinstance(c, str) else c)
    for col in ["open", "high", "low", "close"]:
        if col not in df.columns:
            print("Missing OHLC columns")
            return
    if len(df) < MIN_BACKTEST_DAYS:
        print(f"Need at least {MIN_BACKTEST_DAYS} days, got {len(df)}")
        return

    signals = generate_all_signals(df)
    res = run_backtest_v3(df, signals, initial_balance=INITIAL_BALANCE)
    m = res.metrics
    t = res.trades

    print("=" * 60)
    print("NASDAQ NAS100 — SIGNAL SYSTEM v3.0 — BACKTEST RESULT")
    print("=" * 60)
    print(f"Period: {df.index[0]} to {df.index[-1]} ({len(df)} bars)")
    print(f"Initial balance: ${INITIAL_BALANCE:,.0f}")
    print(f"Final balance:   ${res.final_balance:,.0f}")
    print(f"Signals generated: {len(signals)}")
    print(f"Trades executed:   {len(t) if t is not None and not t.empty else 0}")
    print("-" * 60)
    print("TARGETS vs ACTUAL")
    print("-" * 60)
    print(f"  Signals/day   target >= {TARGETS['signals_per_day_min']}   actual {m.get('signals_per_day', 0):.4f}")
    print(f"  Win rate %    target >= {TARGETS['win_rate_pct_min']}   actual {m.get('win_rate_pct', 0):.2f}")
    print(f"  Monthly ret % target >= {TARGETS['monthly_return_pct_min']}   actual {m.get('monthly_return_pct', 0):.2f}")
    print(f"  Profit factor target >= {TARGETS['profit_factor_min']}   actual {m.get('profit_factor', 0):.2f}")
    print(f"  Max DD %     target <= {TARGETS['max_drawdown_pct_max']}   actual {m.get('max_drawdown_pct', 0):.2f}")
    print(f"  Trade count  min {MIN_TRADES}   actual {m.get('trade_count', 0)}")
    print("-" * 60)
    if res.circuit_breakers_triggered:
        print("Circuit breakers triggered:", res.circuit_breakers_triggered)
    print("=" * 60)

    all_met = (
        m.get("signals_per_day", 0) >= TARGETS["signals_per_day_min"]
        and m.get("win_rate_pct", 0) >= TARGETS["win_rate_pct_min"]
        and m.get("monthly_return_pct", 0) >= TARGETS["monthly_return_pct_min"]
        and m.get("profit_factor", 0) >= TARGETS["profit_factor_min"]
        and m.get("max_drawdown_pct", 100) <= TARGETS["max_drawdown_pct_max"]
        and m.get("trade_count", 0) >= MIN_TRADES
    )
    print("ALL 5 TARGETS + MIN TRADES MET:", "YES" if all_met else "NO")
    print("=" * 60)


if __name__ == "__main__":
    main()
