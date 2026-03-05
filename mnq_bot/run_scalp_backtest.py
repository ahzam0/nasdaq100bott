"""
Backtest the Scalp strategy on historical NQ data.

Uses Yahoo Finance live data (NQ=F). Walks bar-by-bar through 1m candles,
computes volume flow signals, runs detect_scalp(), and simulates entries
with TP1 (partial), TP2, trailing stops, and stop-outs.

Usage:
  python run_scalp_backtest.py                    # last 7 days
  python run_scalp_backtest.py --months 1         # last 1 month (15m expanded)
  python run_scalp_backtest.py --days 30          # 30 days synthetic
  python run_scalp_backtest.py --csv trades.csv   # save trade log
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.disable(logging.WARNING)

from config import (
    SCALP_MAX_TRADES_PER_DAY,
    SCALP_MAX_RISK_PTS,
    SCALP_TP1_PTS,
    SCALP_TP2_PTS,
    SCALP_COOLDOWN_BARS,
    SCALP_MIN_ATR,
    SCALP_MOMENTUM_THRESHOLD,
    TICK_VALUE_USD,
    MAX_RISK_PER_TRADE_USD,
)
from strategy.volume_flow import _candle_proxy_flow, VolumeFlowSignal
from strategy.scalp import detect_scalp, ScalpSetup
from strategy.market_structure import swing_highs_lows

EST = ZoneInfo("America/New_York")

INITIAL_BALANCE = 50_000.0
SESSION_START_MIN = 7 * 60
SESSION_END_MIN = 11 * 60


@dataclass
class ScalpTrade:
    entry_time: datetime
    direction: str
    signal_type: str
    entry: float
    stop: float
    target1: float
    target2: float
    contracts: int
    confidence: str = ""
    notes: str = ""
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl: float = 0.0
    partial_pnl: float = 0.0
    r_multiple: float = 0.0


@dataclass
class ScalpBacktestResult:
    initial_balance: float
    final_balance: float
    total_return_pct: float
    total_trades: int
    winners: int
    losers: int
    win_rate_pct: float
    max_drawdown_pct: float
    max_drawdown_usd: float
    profit_factor: float
    avg_r_per_trade: float
    trades_per_day: float
    avg_hold_bars: float
    trades: list[ScalpTrade] = field(default_factory=list)


def _in_session(t: datetime) -> bool:
    if t.tzinfo is None:
        t = t.replace(tzinfo=EST)
    t = t.astimezone(EST)
    mins = t.hour * 60 + t.minute
    return SESSION_START_MIN <= mins <= SESSION_END_MIN


def _contracts_from_risk(risk_usd: float, risk_pts: float, tick_value: float = TICK_VALUE_USD) -> int:
    if risk_pts <= 0 or tick_value <= 0:
        return 0
    risk_per_contract = risk_pts * tick_value
    return max(1, int(risk_usd / risk_per_contract))


def run_scalp_backtest(
    df_1m: pd.DataFrame,
    df_15m: pd.DataFrame,
    balance: float = INITIAL_BALANCE,
    risk_usd: float = MAX_RISK_PER_TRADE_USD,
    max_trades_per_day: int = SCALP_MAX_TRADES_PER_DAY,
    tp1_pts: float = SCALP_TP1_PTS,
    tp2_pts: float = SCALP_TP2_PTS,
    max_risk_pts: float = SCALP_MAX_RISK_PTS,
    min_atr: float = SCALP_MIN_ATR,
    momentum_threshold: float = SCALP_MOMENTUM_THRESHOLD,
    cooldown_bars: int = SCALP_COOLDOWN_BARS,
    tick_value: float = TICK_VALUE_USD,
) -> ScalpBacktestResult:

    if df_1m.index.tzinfo is None:
        df_1m = df_1m.copy()
        df_1m.index = df_1m.index.tz_localize(EST)
    if df_15m.index.tzinfo is None:
        df_15m = df_15m.copy()
        df_15m.index = df_15m.index.tz_localize(EST)

    current_balance = balance
    peak_balance = balance
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    trades: list[ScalpTrade] = []
    open_trades: list[ScalpTrade] = []
    bars_since_entry = 999
    total_hold_bars = 0

    trading_days = set()

    lookback = 50
    min_bars = max(lookback, 99)

    for i in range(min_bars, len(df_1m)):
        bar_ts = df_1m.index[i]
        bar = df_1m.iloc[i]
        now_est = bar_ts.to_pydatetime() if hasattr(bar_ts, "to_pydatetime") else bar_ts

        if not _in_session(now_est):
            continue

        high = float(bar["high"])
        low = float(bar["low"])
        close = float(bar["close"])
        bars_since_entry += 1

        day_str = now_est.astimezone(EST).strftime("%Y-%m-%d")
        trading_days.add(day_str)

        # Update open trades
        to_close = []
        for t in open_trades:
            if t.direction == "LONG":
                if low <= t.stop:
                    pnl = (t.stop - t.entry) * tick_value * t.contracts
                    current_balance += pnl
                    t.exit_time = now_est
                    t.exit_price = t.stop
                    t.exit_reason = "stop"
                    t.pnl = pnl
                    risk_pts = abs(t.entry - t.stop) or 1
                    t.r_multiple = (t.stop - t.entry) / risk_pts
                    to_close.append(t)
                    continue
                if high >= t.target2:
                    pnl = (t.target2 - t.entry) * tick_value * t.contracts
                    current_balance += pnl
                    t.exit_time = now_est
                    t.exit_price = t.target2
                    t.exit_reason = "tp2"
                    t.pnl = pnl
                    risk_pts = abs(t.entry - t.stop) or 1
                    t.r_multiple = (t.target2 - t.entry) / risk_pts
                    to_close.append(t)
                    continue
                if high >= t.target1 and t.partial_pnl == 0:
                    half = t.contracts // 2
                    if half >= 1:
                        partial = (t.target1 - t.entry) * tick_value * half
                        current_balance += partial
                        t.partial_pnl = partial
                    t.stop = t.entry  # breakeven
            else:
                if high >= t.stop:
                    pnl = (t.entry - t.stop) * tick_value * t.contracts
                    current_balance += pnl
                    t.exit_time = now_est
                    t.exit_price = t.stop
                    t.exit_reason = "stop"
                    t.pnl = pnl
                    risk_pts = abs(t.stop - t.entry) or 1
                    t.r_multiple = (t.entry - t.stop) / risk_pts
                    to_close.append(t)
                    continue
                if low <= t.target2:
                    pnl = (t.entry - t.target2) * tick_value * t.contracts
                    current_balance += pnl
                    t.exit_time = now_est
                    t.exit_price = t.target2
                    t.exit_reason = "tp2"
                    t.pnl = pnl
                    risk_pts = abs(t.stop - t.entry) or 1
                    t.r_multiple = (t.entry - t.target2) / risk_pts
                    to_close.append(t)
                    continue
                if low <= t.target1 and t.partial_pnl == 0:
                    half = t.contracts // 2
                    if half >= 1:
                        partial = (t.entry - t.target1) * tick_value * half
                        current_balance += partial
                        t.partial_pnl = partial
                    t.stop = t.entry

        for t in to_close:
            total_hold_bars += (i - _bar_index_approx(df_1m, t.entry_time, min_bars))
            open_trades.remove(t)
            trades.append(t)

        # Track drawdown
        if current_balance > peak_balance:
            peak_balance = current_balance
        dd = peak_balance - current_balance
        if dd > max_dd_usd:
            max_dd_usd = dd
        dd_pct = (dd / peak_balance * 100) if peak_balance > 0 else 0
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

        # Skip entry check most bars for speed
        if i % 2 != 0:
            continue

        # Cooldown
        if bars_since_entry < cooldown_bars:
            continue

        # Max trades per day
        today = now_est.astimezone(EST).date()
        trades_today = sum(1 for t in trades if t.entry_time.astimezone(EST).date() == today)
        trades_today += len(open_trades)
        if trades_today >= max_trades_per_day:
            continue

        # Don't stack trades
        if len(open_trades) >= 2:
            continue

        # Compute volume flow from candle data
        window = df_1m.iloc[max(0, i - lookback + 1): i + 1]
        flow = _candle_proxy_flow(window, lookback)
        if flow is None:
            continue

        # Get swing structure from 15m
        try:
            loc_15m = df_15m.index.get_indexer([bar_ts], method="ffill")[0]
            lb_15m = df_15m.iloc[max(0, loc_15m - 49): loc_15m + 1]
            if len(lb_15m) < 5:
                continue
            s_highs, s_lows = swing_highs_lows(lb_15m)
        except Exception:
            continue

        setup = detect_scalp(
            window, flow, s_highs, s_lows,
            tp1_pts=tp1_pts,
            tp2_pts=tp2_pts,
            max_risk_pts=max_risk_pts,
            min_atr=min_atr,
            momentum_threshold=momentum_threshold,
        )
        if setup is None:
            continue

        risk_pts = abs(setup.entry_price - setup.stop_price)
        if risk_pts <= 0:
            continue
        contracts = _contracts_from_risk(risk_usd, risk_pts, tick_value)
        if contracts < 1:
            continue

        trade = ScalpTrade(
            entry_time=now_est,
            direction=setup.direction,
            signal_type=setup.signal_type,
            entry=setup.entry_price,
            stop=setup.stop_price,
            target1=setup.target1_price,
            target2=setup.target2_price,
            contracts=contracts,
            confidence=setup.confidence,
            notes=setup.notes,
        )
        open_trades.append(trade)
        bars_since_entry = 0

    # Close remaining open trades at last price
    if open_trades:
        last_close = float(df_1m["close"].iloc[-1])
        last_ts = df_1m.index[-1].to_pydatetime() if hasattr(df_1m.index[-1], "to_pydatetime") else df_1m.index[-1]
        for t in open_trades:
            if t.direction == "LONG":
                pnl = (last_close - t.entry) * tick_value * t.contracts
            else:
                pnl = (t.entry - last_close) * tick_value * t.contracts
            current_balance += pnl
            t.exit_time = last_ts
            t.exit_price = last_close
            t.exit_reason = "eod_close"
            t.pnl = pnl
            risk_pts = abs(t.entry - t.stop) or 1
            if t.direction == "LONG":
                t.r_multiple = (last_close - t.entry) / risk_pts
            else:
                t.r_multiple = (t.entry - last_close) / risk_pts
            trades.append(t)

    n = len(trades)
    winners = sum(1 for t in trades if (t.pnl + t.partial_pnl) > 0)
    losers = n - winners
    win_rate = (100 * winners / n) if n else 0
    gross_profit = sum(t.pnl + t.partial_pnl for t in trades if (t.pnl + t.partial_pnl) > 0)
    gross_loss = abs(sum(t.pnl + t.partial_pnl for t in trades if (t.pnl + t.partial_pnl) < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)
    avg_r = (sum(t.r_multiple for t in trades) / n) if n else 0
    total_return = (current_balance - balance) / balance * 100
    num_days = max(len(trading_days), 1)
    tpd = n / num_days
    avg_hold = (total_hold_bars / n) if n else 0

    return ScalpBacktestResult(
        initial_balance=balance,
        final_balance=current_balance,
        total_return_pct=total_return,
        total_trades=n,
        winners=winners,
        losers=losers,
        win_rate_pct=win_rate,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_usd=max_dd_usd,
        profit_factor=profit_factor,
        avg_r_per_trade=avg_r,
        trades_per_day=tpd,
        avg_hold_bars=avg_hold,
        trades=trades,
    )


def _bar_index_approx(df: pd.DataFrame, dt: datetime, default: int) -> int:
    try:
        idx = df.index.get_indexer([pd.Timestamp(dt)], method="nearest")[0]
        return max(0, idx)
    except Exception:
        return default


def print_report(r: ScalpBacktestResult) -> None:
    profit = r.final_balance - r.initial_balance
    print("\n" + "=" * 60)
    print("  SCALP STRATEGY – BACKTEST REPORT")
    print("=" * 60)
    print(f"  Initial balance:     ${r.initial_balance:,.2f}")
    print(f"  Final balance:       ${r.final_balance:,.2f}")
    print(f"  Net P&L:             ${profit:+,.2f} ({r.total_return_pct:+.2f}%)")
    print("-" * 60)
    print(f"  Total trades:        {r.total_trades} ({r.winners}W / {r.losers}L)")
    print(f"  Win rate:            {r.win_rate_pct:.1f}%")
    print(f"  Trades/day:          {r.trades_per_day:.2f}")
    print(f"  Avg hold (bars):     {r.avg_hold_bars:.0f}")
    print("-" * 60)
    print(f"  Max drawdown:        ${r.max_drawdown_usd:,.2f} ({r.max_drawdown_pct:.2f}%)")
    print(f"  Profit factor:       {r.profit_factor:.2f}")
    print(f"  Avg R per trade:     {r.avg_r_per_trade:.2f}R")
    print("=" * 60)

    # Signal type breakdown
    if r.trades:
        from collections import Counter
        types = Counter(t.signal_type for t in r.trades)
        print("\n  Signal breakdown:")
        for sig, count in types.most_common():
            sig_trades = [t for t in r.trades if t.signal_type == sig]
            sig_wins = sum(1 for t in sig_trades if (t.pnl + t.partial_pnl) > 0)
            sig_pnl = sum(t.pnl + t.partial_pnl for t in sig_trades)
            wr = (100 * sig_wins / count) if count else 0
            print(f"    {sig:<20} {count:>3} trades  WR {wr:>5.1f}%  P&L ${sig_pnl:>+10,.2f}")

        print(f"\n  Last 15 trades:")
        for t in r.trades[-15:]:
            total_pnl = t.pnl + t.partial_pnl
            ts = t.entry_time.strftime("%m/%d %H:%M") if t.entry_time else "?"
            print(f"    {ts}  {t.direction:5}  {t.signal_type:<18}  "
                  f"entry={t.entry:,.0f}  exit={t.exit_price or 0:,.0f}  "
                  f"P&L=${total_pnl:>+8,.2f}  {t.exit_reason}")
    print()


def save_csv(r: ScalpBacktestResult, path: Path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry_time", "direction", "signal_type", "entry", "stop",
                     "tp1", "tp2", "contracts", "confidence", "exit_time",
                     "exit_price", "exit_reason", "pnl", "partial_pnl", "r_multiple", "notes"])
        for t in r.trades:
            w.writerow([
                t.entry_time.isoformat() if t.entry_time else "",
                t.direction, t.signal_type, t.entry, t.stop,
                t.target1, t.target2, t.contracts, t.confidence,
                t.exit_time.isoformat() if t.exit_time else "",
                t.exit_price or "", t.exit_reason,
                round(t.pnl, 2), round(t.partial_pnl, 2),
                round(t.r_multiple, 3), t.notes,
            ])
    print(f"Trades saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="Backtest Scalp Strategy")
    parser.add_argument("--live", action="store_true", help="Use live Yahoo Finance data (NQ=F)")
    parser.add_argument("--months", type=int, default=0, help="Months of live data (default: 7 days)")
    parser.add_argument("--days", type=int, default=30, help="Synthetic data days (if not --live)")
    parser.add_argument("--balance", type=float, default=INITIAL_BALANCE)
    parser.add_argument("--risk", type=float, default=MAX_RISK_PER_TRADE_USD)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--csv", type=str, default="")
    parser.add_argument("--max-trades", type=int, default=SCALP_MAX_TRADES_PER_DAY)
    parser.add_argument("--tp1", type=float, default=SCALP_TP1_PTS)
    parser.add_argument("--tp2", type=float, default=SCALP_TP2_PTS)
    parser.add_argument("--max-risk", type=float, default=SCALP_MAX_RISK_PTS)
    parser.add_argument("--min-atr", type=float, default=SCALP_MIN_ATR)
    parser.add_argument("--momentum", type=float, default=SCALP_MOMENTUM_THRESHOLD)
    parser.add_argument("--cooldown", type=int, default=SCALP_COOLDOWN_BARS)
    args = parser.parse_args()

    df_1m, df_15m = None, None

    if args.live:
        from backtest.live_data import fetch_live_backtest_data
        if args.months >= 1:
            print(f"Fetching live NQ=F data ({args.months} month(s) from Yahoo Finance)...")
            df_1m, df_15m = fetch_live_backtest_data(months=args.months)
        else:
            print("Fetching live NQ=F data (last 7 days from Yahoo Finance)...")
            df_1m, df_15m = fetch_live_backtest_data()
        if df_1m.empty:
            print("ERROR: No data from Yahoo Finance.")
            return 1
        print(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}")
    else:
        from backtest import generate_backtest_data
        print(f"Generating {args.days} days of synthetic data (seed={args.seed})...")
        df_1m, df_15m = generate_backtest_data(trading_days=args.days, seed=args.seed)
        print(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}")

    print(f"\nRunning scalp backtest (balance=${args.balance:,.0f}, risk=${args.risk:.0f}, "
          f"TP1={args.tp1:.0f} TP2={args.tp2:.0f} max_risk={args.max_risk:.0f})...")

    result = run_scalp_backtest(
        df_1m, df_15m,
        balance=args.balance,
        risk_usd=args.risk,
        max_trades_per_day=args.max_trades,
        tp1_pts=args.tp1,
        tp2_pts=args.tp2,
        max_risk_pts=args.max_risk,
        min_atr=args.min_atr,
        momentum_threshold=args.momentum,
        cooldown_bars=args.cooldown,
    )

    print_report(result)

    if args.csv:
        save_csv(result, Path(args.csv))

    return 0


if __name__ == "__main__":
    sys.exit(main())
