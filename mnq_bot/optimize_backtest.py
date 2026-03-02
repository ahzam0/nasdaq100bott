"""
Optimize strategy for best win rate, profit factor, and lowest drawdown.
Runs multiple backtests on live data with different parameter combinations.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import BacktestEngine, BacktestResult
from backtest.live_data import fetch_live_backtest_data


BALANCE = 50_000.0
RISK = 330  # ~$200/day target


def score_result(r: BacktestResult) -> float:
    """Higher is better. Win rate, profit factor, low drawdown, return."""
    wr = r.win_rate_pct / 100.0
    pf = min(r.profit_factor, 5.0)
    dd_penalty = r.max_drawdown_pct / 100.0
    ret = r.total_return_pct / 100.0
    return wr * 0.40 + pf * 0.25 - dd_penalty * 0.25 + max(0, ret) * 0.10


def run_one(
    df_1m,
    df_15m,
    min_rr: float,
    max_trades: int,
    level_tol: float,
    require_trend: bool,
    skip_first: int = 0,
    retest_only: bool = False,
    min_body: float = 0.0,
) -> tuple[BacktestResult, float]:
    engine = BacktestEngine(
        initial_balance=BALANCE,
        risk_per_trade_usd=RISK,
        max_trades_per_day=max_trades,
        min_rr=min_rr,
        level_tolerance_pts=level_tol,
        require_trend_only=require_trend,
        skip_first_minutes=skip_first,
        retest_only=retest_only,
        min_body_pts=min_body,
    )
    result = engine.run(df_1m, df_15m)
    return result, score_result(result)


def main():
    print("Fetching live data...")
    df_1m, df_15m = fetch_live_backtest_data()
    if df_1m.empty or len(df_1m) < 200:
        print("ERROR: Not enough live data.")
        return 1
    print(f"  Bars: 1m={len(df_1m)}, 15m={len(df_15m)}\n")

    # (min_rr, max_trades, level_tol, require_trend, skip_first, retest_only, min_body)
    param_grid = [
        (2.0, 2, 4.0, True, 0, False, 0.0),
        (2.0, 2, 4.0, True, 0, True, 0.0),
        (2.0, 2, 4.0, True, 15, False, 0.0),
        (2.0, 2, 4.0, True, 15, True, 0.0),
        (2.0, 2, 5.0, True, 0, True, 0.0),
        (2.0, 2, 5.0, True, 10, False, 0.0),
        (2.0, 2, 5.0, True, 10, True, 0.0),
        (2.0, 2, 3.0, True, 0, True, 0.0),
        (2.0, 2, 3.0, True, 15, True, 0.0),
        (2.0, 2, 4.0, True, 0, True, 2.0),
        (2.0, 2, 4.0, True, 0, True, 3.0),
        (2.5, 2, 4.0, True, 0, True, 0.0),
        (2.0, 3, 4.0, True, 0, True, 0.0),
        (2.0, 2, 4.0, True, 20, True, 0.0),
    ]

    best_score = -999.0
    best_result: BacktestResult | None = None
    best_params: tuple | None = None
    all_results = []

    for min_rr, max_trades, level_tol, require_trend, skip_first, retest_only, min_body in param_grid:
        try:
            result, score = run_one(
                df_1m, df_15m, min_rr, max_trades, level_tol, require_trend,
                skip_first, retest_only, min_body,
            )
        except Exception as e:
            print(f"  FAIL: {e}")
            continue
        all_results.append((score, result, (min_rr, max_trades, level_tol, require_trend, skip_first, retest_only, min_body)))
        if score > best_score:
            best_score = score
            best_result = result
            best_params = (min_rr, max_trades, level_tol, require_trend, skip_first, retest_only, min_body)
        print(f"  rr={min_rr} mt={max_trades} tol={level_tol} skip={skip_first} retest_only={retest_only} body={min_body} -> WR={result.win_rate_pct:.1f}% PF={result.profit_factor:.2f} DD={result.max_drawdown_pct:.2f}% ret={result.total_return_pct:+.2f}% score={score:.3f}")

    if best_result is None or best_params is None:
        print("No valid results.")
        return 1

    print("\n" + "=" * 60)
    print("  BEST PARAMETERS")
    print("=" * 60)
    min_rr, max_trades, level_tol, require_trend, skip_first, retest_only, min_body = best_params
    print(f"  min_rr={min_rr}, max_trades={max_trades}, level_tol={level_tol}, require_trend={require_trend}")
    print(f"  skip_first_minutes={skip_first}, retest_only={retest_only}, min_body_pts={min_body}")
    print(f"  Win rate:    {best_result.win_rate_pct:.1f}%")
    print(f"  Profit factor: {best_result.profit_factor:.2f}")
    print(f"  Max drawdown:  {best_result.max_drawdown_pct:.2f}% (${best_result.max_drawdown_usd:,.2f})")
    print(f"  Total return:  {best_result.total_return_pct:+.2f}%")
    print(f"  Trades:       {best_result.total_trades} (W={best_result.winners} L={best_result.losers})")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
