"""
Profit-focused optimization: sweep params on 3-month data and pick highest net P&L.
Keeps drawdown under MAX_DD_CAP_PCT so we don't pick an overly risky combo.
Run: python optimize_profit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    MAX_TRADES_PER_DAY,
    REQUIRE_TREND_ONLY,
    SKIP_FIRST_MINUTES,
    MIN_BODY_PTS,
    FALLBACK_AFTER_MINUTES,
    FALLBACK_MIN_RR,
    TARGET_MIN_TRADES_PER_DAY,
)
from backtest import BacktestEngine, BacktestResult
from backtest.live_data import fetch_live_backtest_data

BALANCE = 50_000.0
RISK = 330
MAX_DD_CAP_PCT = 8.0  # Ignore combos with DD above this (sanity cap)


def run_one(
    df_1m,
    df_15m,
    min_rr: float,
    level_tol: float,
    max_risk_pts: float | None,
    retest_only: bool,
) -> BacktestResult:
    engine = BacktestEngine(
        initial_balance=BALANCE,
        risk_per_trade_usd=RISK,
        max_trades_per_day=MAX_TRADES_PER_DAY,
        min_rr=min_rr,
        level_tolerance_pts=level_tol,
        require_trend_only=REQUIRE_TREND_ONLY,
        skip_first_minutes=SKIP_FIRST_MINUTES,
        retest_only=retest_only,
        min_body_pts=MIN_BODY_PTS,
        max_risk_pts=max_risk_pts,
        fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
        fallback_min_rr=FALLBACK_MIN_RR if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
    )
    return engine.run(df_1m, df_15m)


def main():
    print("Fetching 3-month live data (Yahoo NQ=F)...")
    df_1m, df_15m = fetch_live_backtest_data(months=3)
    if df_1m.empty or len(df_1m) < 500:
        print("ERROR: Not enough data.")
        return 1
    print(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}\n")

    # Grid: prioritize more trades / slightly looser filters for higher profit
    # max_risk_pts: larger = more trades, more DD. None = no cap (engine may use 500 cap elsewhere - check)
    max_risk_pts_list = [350.0, 400.0, 500.0]
    min_rr_list = [1.7, 1.8]
    level_tol_list = [6.0, 8.0]
    retest_only_list = [True, False]  # False = allow Failed Breakout = more setups

    best_profit = -999_999.0
    best_result: BacktestResult | None = None
    best_params: dict | None = None
    results = []

    for max_rp in max_risk_pts_list:
        for min_rr in min_rr_list:
            for level_tol in level_tol_list:
                for retest_only in retest_only_list:
                    try:
                        r = run_one(
                            df_1m, df_15m,
                            min_rr=min_rr,
                            level_tol=level_tol,
                            max_risk_pts=max_rp,
                            retest_only=retest_only,
                        )
                    except Exception as e:
                        print(f"  FAIL max_rp={max_rp} min_rr={min_rr} tol={level_tol} retest_only={retest_only}: {e}")
                        continue
                    profit = r.final_balance - r.initial_balance
                    if r.max_drawdown_pct > MAX_DD_CAP_PCT:
                        continue  # skip overly risky
                    results.append((profit, r.max_drawdown_pct, r, (max_rp, min_rr, level_tol, retest_only)))
                    if profit > best_profit:
                        best_profit = profit
                        best_result = r
                        best_params = {"max_risk_pts": max_rp, "min_rr": min_rr, "level_tol": level_tol, "retest_only": retest_only}
                    print(
                        f"  max_rp={max_rp} min_rr={min_rr} tol={level_tol} retest={retest_only} -> "
                        f"P&L=${profit:+,.0f} DD={r.max_drawdown_pct:.2f}% trades={r.total_trades} WR={r.win_rate_pct:.1f}%"
                    )

    if best_result is None or best_params is None:
        print("\nNo valid combo within DD cap.")
        return 1

    print("\n" + "=" * 60)
    print("  BEST FOR PROFIT (DD <= {}%)".format(MAX_DD_CAP_PCT))
    print("=" * 60)
    print(f"  MAX_RISK_PTS = {best_params['max_risk_pts']}")
    print(f"  MIN_RR_RATIO = {best_params['min_rr']}")
    print(f"  LEVEL_TOLERANCE_PTS = {best_params['level_tol']}")
    print(f"  RETEST_ONLY = {best_params['retest_only']}")
    print(f"  Net P&L:     ${best_profit:+,.2f}")
    print(f"  Total return: {best_result.total_return_pct:+.2f}%")
    print(f"  Trades:       {best_result.total_trades} (W={best_result.winners} L={best_result.losers})")
    print(f"  Win rate:     {best_result.win_rate_pct:.1f}%")
    print(f"  Profit factor: {best_result.profit_factor:.2f}")
    print(f"  Max drawdown: {best_result.max_drawdown_pct:.2f}% (${best_result.max_drawdown_usd:,.2f})")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
