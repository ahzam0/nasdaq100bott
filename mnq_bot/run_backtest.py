"""
Run backtest of Riley Coleman MNQ strategy with $50,000 starting balance.
Usage:
  Synthetic data:   python run_backtest.py [--days 30] [--risk 75]
  Historical (Yahoo): python run_backtest.py --live [--months 3] [--risk 330]
  Real-time feed:   python run_backtest.py --realtime [--loop 60]
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

# Project root on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    LEVEL_TOLERANCE_PTS,
    MAX_RISK_PTS,
    MAX_RISK_PER_TRADE_USD,
    MAX_TRADES_PER_DAY,
    MIN_RR_RATIO,
    REQUIRE_TREND_ONLY,
    RETEST_ONLY,
    SKIP_FIRST_MINUTES,
    MIN_BODY_PTS,
    BROKER,
    USE_LIVE_FEED,
    PRICE_API_URL,
    TARGET_MIN_TRADES_PER_DAY,
    FALLBACK_AFTER_MINUTES,
    FALLBACK_MIN_RR,
)
from backtest import BacktestEngine, BacktestResult, generate_backtest_data
from backtest.live_data import fetch_live_backtest_data, _session_filter


INITIAL_BALANCE = 50_000.0
RISK_PER_TRADE = MAX_RISK_PER_TRADE_USD  # Match config so backtest default = bot risk
DEFAULT_DAYS = 30


def print_report(r: BacktestResult) -> None:
    print("\n" + "=" * 60)
    print("  MNQ RILEY COLEMAN STRATEGY – BACKTEST REPORT")
    print("=" * 60)
    profit_usd = r.final_balance - r.initial_balance
    print(f"  Initial balance:     ${r.initial_balance:,.2f}")
    print(f"  Final balance:       ${r.final_balance:,.2f}")
    print(f"  Net P&L:             ${profit_usd:+,.2f}")
    print(f"  Profit amount:       ${profit_usd:+,.2f}  (total return {r.total_return_pct:+.2f}%)")
    print(f"  Total return:        {r.total_return_pct:+.2f}%")
    print("-" * 60)
    print(f"  Total trades:        {r.total_trades}")
    print(f"  Winners:             {r.winners}")
    print(f"  Losers:              {r.losers}")
    print(f"  Win rate:            {r.win_rate_pct:.1f}%")
    print("-" * 60)
    print(f"  Max drawdown:        ${r.max_drawdown_usd:,.2f} ({r.max_drawdown_pct:.2f}%)")
    print(f"  Profit factor:       {r.profit_factor:.2f}")
    print(f"  Avg R per trade:     {r.avg_r_per_trade:.2f}R")
    print("=" * 60)
    if r.trades:
        print("\n  Last 10 trades:")
        for t in r.trades[-10:]:
            pnl = t.pnl + t.partial_pnl
            print(f"    {t.entry_time.strftime('%Y-%m-%d %H:%M')}  {t.direction:5}  entry={t.entry:,.2f}  exit={t.exit_price or 0:,.2f}  P&L=${pnl:+,.2f}  {t.exit_reason}")
    print()


def save_trades_csv(r: BacktestResult, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "entry_time", "direction", "entry", "stop", "target1", "target2",
            "contracts", "exit_time", "exit_price", "exit_reason", "pnl", "partial_pnl", "r_multiple",
        ])
        for t in r.trades:
            w.writerow([
                t.entry_time.isoformat(),
                t.direction,
                t.entry,
                t.stop,
                t.target1,
                t.target2,
                t.contracts,
                t.exit_time.isoformat() if t.exit_time else "",
                t.exit_price or "",
                t.exit_reason,
                t.pnl,
                t.partial_pnl,
                t.r_multiple,
            ])
    print(f"Trades saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="Backtest MNQ Riley Coleman strategy")
    parser.add_argument("--live", action="store_true", help="Use live market data from Yahoo Finance (NQ=F)")
    parser.add_argument("--months", type=int, default=0, metavar="N", help="With --live: use 1 month of data (15m expanded to 1m). Default: 7 days 1m.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Trading days (synthetic only)")
    parser.add_argument("--risk", type=float, default=RISK_PER_TRADE, help="Risk per trade in USD")
    parser.add_argument("--balance", type=float, default=INITIAL_BALANCE, help="Starting balance")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for synthetic data")
    parser.add_argument("--csv", type=str, default="", help="Save trades to this CSV path")
    parser.add_argument("--save-data", type=str, default="", metavar="PREFIX", help="With --live: save 1m/15m data to PREFIX_1m.csv, PREFIX_15m.csv for replay")
    parser.add_argument("--load-data", type=str, default="", metavar="PREFIX", help="Load 1m/15m from PREFIX_1m.csv, PREFIX_15m.csv and run backtest (replay)")
    parser.add_argument("--max-trades", type=int, default=None, metavar="N", help="Max trades per day (default: config). Lower = less exposure, often lower DD.")
    parser.add_argument("--skip-first", type=int, default=None, metavar="MIN", help="Skip first N min of session (default: config). e.g. 15 = fewer weak opens.")
    parser.add_argument("--min-rr", type=float, default=None, metavar="R", help="Min R:R required (default: config). e.g. 2.5 = stricter.")
    parser.add_argument("--min-body", type=float, default=None, metavar="PTS", help="Min reversal candle body in points (default: config). e.g. 2 = filter weak setups.")
    parser.add_argument("--level-tol", type=float, default=None, metavar="PTS", help="Level tolerance in points (default: config).")
    parser.add_argument("--max-dd-pct", type=float, default=None, metavar="PCT", help="Cap drawdown: stop new entries when DD from peak >= this % (e.g. 10). Reduces max DD.")
    parser.add_argument("--max-risk-pts", type=float, default=None, metavar="PTS", help="Skip trades with stop wider than this (points). Limits loss per trade and reduces DD.")
    parser.add_argument("--realtime", action="store_true", help="Use real-time data from live feed (same as bot: Yahoo/Price API/Tradovate). Fetches latest 1m/15m and runs backtest.")
    parser.add_argument("--loop", type=int, default=0, metavar="SEC", help="With --realtime: re-run backtest every SEC seconds (e.g. 60). 0 = run once.")
    parser.add_argument("--use-orderflow-proxy", action="store_true", help="Use candle-based order flow proxy in backtest (require bar direction to confirm LONG/SHORT; aligns with live when USE_ORDERFLOW).")
    parser.add_argument("--session-24-7", action="store_true", help="Scan/trade 24/7 (no 7–11 EST filter). For testing only.")
    parser.add_argument("--session-ist", action="store_true", help="Session 8:00 PM–11:30 PM India Standard Time (IST).")
    parser.add_argument("--session-start", type=str, default="", metavar="HH:MM", help="EST session start (e.g. 07:00). With --session-end, overrides default 7-11.")
    parser.add_argument("--session-end", type=str, default="", metavar="HH:MM", help="EST session end (e.g. 11:00). With --session-start.")
    args = parser.parse_args()

    def _parse_session_min(s: str) -> int | None:
        if not s or ":" not in s:
            return None
        parts = s.strip().split(":")
        if len(parts) != 2:
            return None
        try:
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h * 60 + m
        except ValueError:
            pass
        return None

    session_start_min = _parse_session_min(args.session_start)
    session_end_min = _parse_session_min(args.session_end)
    use_custom_session = session_start_min is not None and session_end_min is not None and session_start_min < session_end_min

    df_1m, df_15m = None, None
    if args.load_data:
        import pandas as pd
        p = Path(args.load_data)
        path_1m = p if str(p).endswith("_1m.csv") else Path(str(args.load_data).rstrip("_") + "_1m.csv")
        path_15m = p if str(p).endswith("_15m.csv") else Path(str(args.load_data).rstrip("_") + "_15m.csv")
        if not path_1m.exists():
            path_1m = Path(args.load_data + "_1m.csv")
        if not path_15m.exists():
            path_15m = Path(args.load_data + "_15m.csv")
        if not path_1m.exists() or not path_15m.exists():
            print(f"ERROR: Load data not found: {path_1m} / {path_15m}")
            return 1
        df_1m = pd.read_csv(path_1m, index_col=0, parse_dates=True)
        df_15m = pd.read_csv(path_15m, index_col=0, parse_dates=True)
        if df_1m.index.tzinfo is None and hasattr(df_1m.index, "tz_localize"):
            try:
                from zoneinfo import ZoneInfo
                df_1m = df_1m.tz_localize(ZoneInfo("America/New_York"))
                df_15m = df_15m.tz_localize(ZoneInfo("America/New_York"))
            except Exception:
                pass
        print(f"Loaded replay data: 1m bars={len(df_1m)}, 15m bars={len(df_15m)}")

    # Real-time: use live feed (same as bot); optionally re-run every N seconds
    if args.realtime and args.loop > 0:
        from data import get_feed
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        engine = BacktestEngine(
            initial_balance=args.balance,
            risk_per_trade_usd=args.risk,
            max_trades_per_day=args.max_trades if args.max_trades is not None else MAX_TRADES_PER_DAY,
            min_rr=args.min_rr if args.min_rr is not None else MIN_RR_RATIO,
            level_tolerance_pts=args.level_tol if args.level_tol is not None else LEVEL_TOLERANCE_PTS,
            require_trend_only=REQUIRE_TREND_ONLY,
            skip_first_minutes=args.skip_first if args.skip_first is not None else SKIP_FIRST_MINUTES,
            retest_only=RETEST_ONLY,
            min_body_pts=args.min_body if args.min_body is not None else MIN_BODY_PTS,
            max_drawdown_cap_pct=args.max_dd_pct,
            max_risk_pts=args.max_risk_pts if args.max_risk_pts is not None else MAX_RISK_PTS,
            fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
            fallback_min_rr=FALLBACK_MIN_RR if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
        )
        try:
            while True:
                df_1m = feed.get_1m_candles(500)
                df_15m = feed.get_15m_candles(100)
                df_1m = _session_filter(df_1m) if not df_1m.empty else df_1m
                df_15m = _session_filter(df_15m) if not df_15m.empty else df_15m
                if df_1m.empty or len(df_1m) < 100:
                    print("Waiting for enough 1m bars (session 7-11 EST)...")
                    time.sleep(args.loop)
                    continue
                print(f"\n[Real-time] 1m bars={len(df_1m)}, 15m bars={len(df_15m)}")
                result = engine.run(df_1m, df_15m)
                print_report(result)
                time.sleep(args.loop)
        except KeyboardInterrupt:
            print("\nStopped.")
        return 0

    if args.realtime:
        from data import get_feed
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        df_1m = feed.get_1m_candles(500)
        df_15m = feed.get_15m_candles(100)
        if df_1m.empty or df_15m.empty:
            print("ERROR: No data from live feed. Check internet and that market data is available (e.g. yfinance for NQ=F).")
            return 1
        df_1m = _session_filter(df_1m)
        df_15m = _session_filter(df_15m)
        if len(df_1m) < 100:
            print("ERROR: Need at least 100 1m bars (session 7-11 EST). Try again during/after session.")
            return 1
        print("Using real-time data from live feed (session 7-11 EST)...")
        print(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}")

    if df_1m is None and args.live:
        fetch_24_7 = args.session_24_7 or use_custom_session
        session_note = "24/7 (all hours)" if fetch_24_7 else ("IST 8PM–11:30PM" if args.session_ist else "session 7-11 EST")
        if args.months and args.months >= 1:
            print(f"Fetching live market data from Yahoo Finance (NQ=F, last {args.months} month(s), 15m->1m, {session_note})...")
            df_1m, df_15m = fetch_live_backtest_data(months=args.months, session_24_7=fetch_24_7, session_ist=args.session_ist)
        else:
            print(f"Fetching live market data from Yahoo Finance (NQ=F, last 7 days, {session_note})...")
            df_1m, df_15m = fetch_live_backtest_data(session_24_7=fetch_24_7, session_ist=args.session_ist)
        if df_1m.empty:
            print("ERROR: No 1m data received. Check internet and yfinance (pip install yfinance).")
            return 1
        print(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}")
        if args.save_data:
            prefix = args.save_data.rstrip("_")
            path_1m = Path(prefix + "_1m.csv")
            path_15m = Path(prefix + "_15m.csv")
            df_1m.to_csv(path_1m)
            df_15m.to_csv(path_15m)
            print(f"  Data saved: {path_1m}, {path_15m}")
    if df_1m is None:
        print(f"Generating {args.days} trading days of 1m/15m data (seed={args.seed})...")
        df_1m, df_15m = generate_backtest_data(trading_days=args.days, seed=args.seed)
        print(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}")
    else:
        pass  # already set from --load-data

    engine = BacktestEngine(
        initial_balance=args.balance,
        risk_per_trade_usd=args.risk,
        max_trades_per_day=args.max_trades if args.max_trades is not None else MAX_TRADES_PER_DAY,
        min_rr=args.min_rr if args.min_rr is not None else MIN_RR_RATIO,
        level_tolerance_pts=args.level_tol if args.level_tol is not None else LEVEL_TOLERANCE_PTS,
        require_trend_only=REQUIRE_TREND_ONLY,
        skip_first_minutes=args.skip_first if args.skip_first is not None else SKIP_FIRST_MINUTES,
        retest_only=RETEST_ONLY,
        min_body_pts=args.min_body if args.min_body is not None else MIN_BODY_PTS,
        max_drawdown_cap_pct=args.max_dd_pct,
        max_risk_pts=args.max_risk_pts if args.max_risk_pts is not None else MAX_RISK_PTS,
        fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
        fallback_min_rr=FALLBACK_MIN_RR if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
        use_orderflow_proxy=args.use_orderflow_proxy,
        session_24_7=args.session_24_7,
        session_ist=args.session_ist,
        session_start_min=session_start_min if use_custom_session else None,
        session_end_min=session_end_min if use_custom_session else None,
    )
    dd_cap_msg = f", DD cap={args.max_dd_pct}%" if args.max_dd_pct is not None else ""
    of_msg = " (order flow proxy ON)" if args.use_orderflow_proxy else ""
    risk_pts_msg = f", max risk pts={args.max_risk_pts}" if args.max_risk_pts is not None else ""
    print(f"Running backtest (balance=${args.balance:,.0f}, risk=${args.risk:.0f}/trade{dd_cap_msg}{risk_pts_msg}{of_msg})...")
    result = engine.run(df_1m, df_15m)

    if args.realtime:
        print("  Data source: Live feed (real-time, session 7-11 EST)")
    elif args.live:
        if use_custom_session:
            session_note = f"EST {args.session_start}-{args.session_end}"
        else:
            session_note = "24/7" if args.session_24_7 else ("IST 8PM–11:30PM" if args.session_ist else "7-11 EST")
        src = f"Yahoo Finance (NQ=F, last {args.months} month(s), {session_note})" if args.months and args.months >= 1 else f"Yahoo Finance (NQ=F, last 7 days, {session_note})"
        print(f"  Data source: {src}")
    print_report(result)
    if args.csv:
        save_trades_csv(result, Path(args.csv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
