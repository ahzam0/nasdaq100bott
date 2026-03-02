"""
Full optimization to improve backtest stats: P&L, return, win rate, PF, lower DD.
Sweeps risk, min_rr, level_tol, max_risk_pts, skip_first on 3-month data.
Run: python optimize_stats.py
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
    FALLBACK_AFTER_MINUTES,
    FALLBACK_MIN_RR,
    TARGET_MIN_TRADES_PER_DAY,
)
from backtest import BacktestEngine, BacktestResult
from backtest.live_data import fetch_live_backtest_data

BALANCE = 50_000.0
MAX_DD_CAP_PCT = 8.0
MIN_TRADES = 25


def run_one(df_1m, df_15m, risk, min_rr, level_tol, max_rp, skip_first, retest_only=True, min_body=0.0):
    engine = BacktestEngine(
        initial_balance=BALANCE,
        risk_per_trade_usd=risk,
        max_trades_per_day=MAX_TRADES_PER_DAY,
        min_rr=min_rr,
        level_tolerance_pts=level_tol,
        require_trend_only=REQUIRE_TREND_ONLY,
        skip_first_minutes=skip_first,
        retest_only=retest_only,
        min_body_pts=min_body,
        max_risk_pts=max_rp,
        fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
        fallback_min_rr=FALLBACK_MIN_RR if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
    )
    return engine.run(df_1m, df_15m)


def score(r: BacktestResult) -> float:
    """Higher = better: profit, return, WR, PF; penalize DD."""
    if r.total_trades < MIN_TRADES or r.max_drawdown_pct > MAX_DD_CAP_PCT:
        return -999_999.0
    profit = r.final_balance - r.initial_balance
    ret = r.total_return_pct / 100.0
    wr = r.win_rate_pct / 100.0
    pf = min(r.profit_factor, 10.0)
    dd = r.max_drawdown_pct / 100.0
    return profit * 0.35 + ret * 3000 + wr * 800 + pf * 120 - dd * 400


def main():
    print("Fetching 3 months live data...")
    df_1m, df_15m = fetch_live_backtest_data(months=3)
    if df_1m.empty or len(df_1m) < 500:
        print("ERROR: Not enough data.")
        return 1
    print(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}\n")

    # Grid: maximize P&L, WR, PF; keep DD under cap
    grid = []
    for risk in [370, 380, 400]:
        for min_rr in [1.75, 1.8]:
            for level_tol in [7.0, 8.0, 9.0]:
                for max_rp in [350.0, 400.0]:
                    for skip_first in [0]:
                        grid.append((risk, min_rr, level_tol, max_rp, skip_first))

    best_score = -999_999.0
    best_r: BacktestResult | None = None
    best_p: tuple | None = None

    for i, (risk, min_rr, level_tol, max_rp, skip_first) in enumerate(grid):
        try:
            r = run_one(df_1m, df_15m, risk, min_rr, level_tol, max_rp, skip_first)
        except Exception as e:
            continue
        s = score(r)
        if s > best_score:
            best_score = s
            best_r = r
            best_p = (risk, min_rr, level_tol, max_rp, skip_first)
        if (i + 1) % 50 == 0 or s > best_score - 0.01:
            profit = r.final_balance - r.initial_balance
            print(f"  [{i+1}/{len(grid)}] risk={risk} rr={min_rr} tol={level_tol} max_rp={max_rp} skip={skip_first} -> P&L=${profit:+,.0f} WR={r.win_rate_pct:.1f}% DD={r.max_drawdown_pct:.2f}% PF={r.profit_factor:.2f} score={s:.1f}")

    if best_r is None or best_p is None:
        print("No valid result.")
        return 1

    risk, min_rr, level_tol, max_rp, skip_first = best_p
    profit = best_r.final_balance - best_r.initial_balance

    print("\n" + "=" * 60)
    print("  BEST PARAMS (improved stats)")
    print("=" * 60)
    print(f"  MAX_RISK_PER_TRADE_USD = {risk}")
    print(f"  MIN_RR_RATIO = {min_rr}")
    print(f"  LEVEL_TOLERANCE_PTS = {level_tol}")
    print(f"  MAX_RISK_PTS = {max_rp}")
    print(f"  SKIP_FIRST_MINUTES = {skip_first}")
    print(f"  Net P&L:     ${profit:+,.2f} ({best_r.total_return_pct:+.2f}%)")
    print(f"  Trades:      {best_r.total_trades} (W={best_r.winners} L={best_r.losers})")
    print(f"  Win rate:    {best_r.win_rate_pct:.1f}%")
    print(f"  Profit factor: {best_r.profit_factor:.2f}")
    print(f"  Max drawdown: {best_r.max_drawdown_pct:.2f}%")
    print("=" * 60)

    # Update config
    config_path = ROOT / "config.py"
    text = config_path.read_text(encoding="utf-8")
    import re
    for name, val in [
        ("MAX_RISK_PER_TRADE_USD", int(risk)),
        ("MIN_RR_RATIO", min_rr),
        ("LEVEL_TOLERANCE_PTS", level_tol),
        ("MAX_RISK_PTS", max_rp),
        ("SKIP_FIRST_MINUTES", int(skip_first)),
    ]:
        text = re.sub(rf"^(\s*{re.escape(name)}\s*=\s*)[^\n]+", rf"\g<1>{val}", text, flags=re.MULTILINE)
    config_path.write_text(text, encoding="utf-8")
    print(f"\nUpdated {config_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
