"""
Hit-and-try: run backtest on many EST session windows and report the most profitable.
Uses 3-month live data (Yahoo NQ=F), fetches once 24/7 then filters by session in engine.

Run from mnq_bot:  python scripts/best_session_scan.py [--months 3] [--risk 380]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import BacktestEngine
from backtest.live_data import fetch_live_backtest_data
from config import (
    LEVEL_TOLERANCE_PTS,
    MAX_RISK_PTS,
    MAX_TRADES_PER_DAY,
    MIN_RR_RATIO,
    REQUIRE_TREND_ONLY,
    RETEST_ONLY,
    SKIP_FIRST_MINUTES,
    MIN_BODY_PTS,
    TARGET_MIN_TRADES_PER_DAY,
    FALLBACK_AFTER_MINUTES,
    FALLBACK_MIN_RR,
)

INITIAL_BALANCE = 50_000.0


def _min_to_str(m: int) -> str:
    h, mn = m // 60, m % 60
    return f"{h:02d}:{mn:02d}"


# EST session windows to try (start_min, end_min); at least 1 hour; cover 6:00-11:00
SESSION_WINDOWS: list[tuple[int, int]] = []
for start_h in range(6, 10):
    for end_h in range(start_h + 1, 12):
        SESSION_WINDOWS.append((start_h * 60, end_h * 60))
# Add 9:30-11
SESSION_WINDOWS.append((9 * 60 + 30, 11 * 60))
SESSION_WINDOWS.sort(key=lambda x: (x[0], x[1]))


def main():
    parser = argparse.ArgumentParser(description="Find most profitable session (EST) via backtest")
    parser.add_argument("--months", type=int, default=3, help="Months of live data")
    parser.add_argument("--risk", type=float, default=380.0, help="Risk per trade USD")
    parser.add_argument("--balance", type=float, default=INITIAL_BALANCE, help="Starting balance")
    args = parser.parse_args()

    print("Fetching 3-month live data (NQ=F, 24/7)...")
    df_1m, df_15m = fetch_live_backtest_data(months=args.months, session_24_7=True)
    if df_1m.empty or len(df_1m) < 500:
        print("ERROR: Not enough data.")
        return 1
    print(f"  Loaded {len(df_1m)} x 1m bars, {len(df_15m)} x 15m bars\n")

    results: list[tuple[str, float, float, float, float, int]] = []
    for start_min, end_min in SESSION_WINDOWS:
        label = f"{_min_to_str(start_min)}-{_min_to_str(end_min)} EST"
        engine = BacktestEngine(
            initial_balance=args.balance,
            risk_per_trade_usd=args.risk,
            max_trades_per_day=MAX_TRADES_PER_DAY,
            min_rr=MIN_RR_RATIO,
            level_tolerance_pts=LEVEL_TOLERANCE_PTS,
            require_trend_only=REQUIRE_TREND_ONLY,
            skip_first_minutes=SKIP_FIRST_MINUTES,
            retest_only=RETEST_ONLY,
            min_body_pts=MIN_BODY_PTS,
            max_risk_pts=MAX_RISK_PTS,
            fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
            fallback_min_rr=FALLBACK_MIN_RR if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
            session_24_7=False,
            session_ist=False,
            session_start_min=start_min,
            session_end_min=end_min,
        )
        result = engine.run(df_1m, df_15m)
        net_pnl = result.final_balance - result.initial_balance
        results.append((
            label,
            result.total_return_pct,
            net_pnl,
            result.win_rate_pct,
            result.max_drawdown_pct,
            result.total_trades,
        ))

    results.sort(key=lambda x: x[1], reverse=True)

    print("=" * 72)
    print("  SESSION SCAN – 3-month live data, sorted by total return %")
    print("=" * 72)
    print(f"  {'Session (EST)':<18} {'Return %':>10} {'Net P&L':>12} {'Win%':>6} {'MaxDD%':>7} {'Trades':>6}")
    print("-" * 72)
    for label, ret_pct, pnl, wr, dd_pct, n in results:
        print(f"  {label:<18} {ret_pct:>+9.2f}% ${pnl:>+10,.0f} {wr:>5.1f}% {dd_pct:>6.2f}% {n:>6}")
    print("=" * 72)
    best = results[0]
    print(f"\n  >>> BEST SESSION: {best[0]}  (return {best[1]:+.2f}%, P&L ${best[2]:+,.0f}, {best[5]} trades)")
    bstart, bend = best[0].replace(" EST", "").split("-")
    print(f"  Run with:  py -3 run_backtest.py --live --months 3 --risk {args.risk:.0f} --session-start {bstart} --session-end {bend}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
