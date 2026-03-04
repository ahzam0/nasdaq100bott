"""
Hit-and-try optimizer: find parameters for >=40% return, ~70% win rate,
maximum trades, lowest max drawdown. Uses parallel backtests (multiprocessing).
Run: python optimize_40pct.py [--workers 8] [--rounds 2]
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import BacktestEngine, BacktestResult
from backtest.live_data import fetch_live_backtest_data
from config import (
    REQUIRE_TREND_ONLY,
    RETEST_ONLY,
    TARGET_MIN_TRADES_PER_DAY,
    FALLBACK_AFTER_MINUTES,
    FALLBACK_MIN_RR,
    TICK_VALUE_USD,
)

BALANCE = 50_000.0
TARGET_RETURN_PCT = 40.0
TARGET_WR_LOW = 65.0
TARGET_WR_HIGH = 75.0
MIN_TRADES = 10  # Need enough trades for stats


def run_one_backtest(params: dict, df_1m, df_15m) -> tuple[dict, BacktestResult]:
    """Run a single backtest with given params. Returns (params, result)."""
    engine = BacktestEngine(
        initial_balance=params.get("balance", BALANCE),
        risk_per_trade_usd=params.get("risk", 330),
        max_trades_per_day=params.get("max_trades_per_day", 3),
        min_rr=params.get("min_rr", 1.75),
        level_tolerance_pts=params.get("level_tol", 6.0),
        require_trend_only=params.get("require_trend_only", REQUIRE_TREND_ONLY),
        skip_first_minutes=params.get("skip_first", 0),
        retest_only=params.get("retest_only", RETEST_ONLY),
        min_body_pts=params.get("min_body", 0.0),
        max_drawdown_cap_pct=params.get("max_dd_cap_pct"),
        max_risk_pts=params.get("max_risk_pts", 350.0),
        fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
        fallback_min_rr=params.get("fallback_min_rr", FALLBACK_MIN_RR) if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
        use_orderflow_proxy=params.get("use_orderflow_proxy", False),
    )
    result = engine.run(df_1m, df_15m)
    return (params, result)


def run_chunk(args):
    """Worker: run a chunk of param sets on same data. Returns list of (params, result)."""
    chunk_params, df_1m, df_15m = args
    out = []
    for p in chunk_params:
        try:
            out.append(run_one_backtest(p, df_1m, df_15m))
        except Exception:
            pass
    return out


def generate_params(n: int, seed: int = 42) -> list[dict]:
    """Generate n random parameter combinations for hit-and-try. Biased toward known-good region (1.8 rr, 6-8 tol, 200-350 pts)."""
    rng = random.Random(seed)
    params_list = []
    # Include doc's best combo (BACKTEST_3M_RESULT: +44%, 64.7% WR)
    params_list.append({
        "risk": 380, "min_rr": 1.8, "level_tol": 8.0, "max_risk_pts": 350.0,
        "max_trades_per_day": 3, "skip_first": 0, "min_body": 0.0,
        "retest_only": True, "require_trend_only": True, "max_dd_cap_pct": None, "fallback_min_rr": FALLBACK_MIN_RR,
    })
    for _ in range(n - 1):
        # Bias toward 1.7-2.0 rr, 6-9 level_tol, 200-350 max_risk_pts
        p = {
            "risk": round(rng.uniform(330, 400), 0),
            "min_rr": round(rng.uniform(1.65, 2.2), 2),
            "level_tol": round(rng.uniform(5.0, 9.0), 1),
            "max_risk_pts": round(rng.uniform(150, 350), 0) if rng.random() > 0.15 else 350.0,
            "max_trades_per_day": rng.randint(2, 4),
            "skip_first": rng.randint(0, 15) if rng.random() > 0.5 else 0,
            "min_body": round(rng.uniform(0, 2.5), 1) if rng.random() > 0.6 else 0.0,
            "retest_only": rng.choice([True, False]),
            "require_trend_only": rng.choice([True, True, False]),  # prefer True
            "max_dd_cap_pct": round(rng.uniform(4, 10), 1) if rng.random() > 0.5 else None,
            "fallback_min_rr": round(rng.uniform(1.5, 1.85), 2) if rng.random() > 0.4 else FALLBACK_MIN_RR,
        }
        if p["max_risk_pts"] is not None and p["max_risk_pts"] < 80:
            p["max_risk_pts"] = 150
        params_list.append(p)
    return params_list


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Optimize for 40%+ return, ~70% WR, min DD, max trades")
    parser.add_argument("--workers", type=int, default=4, help="Parallel workers (default 4). Use 1 for no multiprocessing.")
    parser.add_argument("--rounds", type=int, default=2, help="Number of optimization rounds (each round = 120 combos)")
    parser.add_argument("--months", type=int, default=3, help="Months of Yahoo data (default 3)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--combos", type=int, default=0, help="Combos per round (default 120). Use 40 for quick test.")
    args = parser.parse_args()
    n_per_round = args.combos if args.combos > 0 else 120

    def log(msg):
        print(msg)
        sys.stdout.flush()

    log("Fetching live data (Yahoo NQ=F)...")
    df_1m, df_15m = fetch_live_backtest_data(months=args.months)
    if df_1m.empty or len(df_1m) < 500:
        log("ERROR: Not enough data.")
        return 1
    log(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}\n")

    all_results = []
    for round_num in range(1, args.rounds + 1):
        params_list = generate_params(n_per_round, seed=args.seed + round_num * 1000)

        if args.workers <= 1:
            # Single process: no multiprocessing (reliable on Windows)
            log(f"Round {round_num}: running {len(params_list)} backtests (single process)...")
            for i, p in enumerate(params_list):
                try:
                    _, result = run_one_backtest(p, df_1m, df_15m)
                    all_results.append((p, result))
                except Exception:
                    pass
                if (i + 1) % 20 == 0:
                    log(f"  {i + 1}/{len(params_list)} done...")
        else:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            chunk_size = max(1, len(params_list) // args.workers)
            chunks = [
                params_list[i : i + chunk_size]
                for i in range(0, len(params_list), chunk_size)
            ]
            chunk_args = [(c, df_1m, df_15m) for c in chunks]
            log(f"Round {round_num}: running {len(params_list)} backtests ({args.workers} workers)...")
            with ProcessPoolExecutor(max_workers=args.workers) as ex:
                futures = [ex.submit(run_chunk, a) for a in chunk_args]
                for fut in as_completed(futures):
                    try:
                        chunk_out = fut.result()
                        for params, result in chunk_out:
                            all_results.append((params, result))
                    except Exception as e:
                        log(f"  Worker error: {e}")

    # Filter: return >= 40%, win rate 65-75%, enough trades
    candidates = [
        (p, r) for p, r in all_results
        if r.total_return_pct >= TARGET_RETURN_PCT
        and TARGET_WR_LOW <= r.win_rate_pct <= TARGET_WR_HIGH
        and r.total_trades >= MIN_TRADES
    ]

    # Sort by: lower DD first, then more trades, then higher return
    candidates.sort(
        key=lambda x: (x[1].max_drawdown_pct, -x[1].total_trades, -x[1].total_return_pct)
    )

    if not candidates:
        # Relax: try return >= 30% and WR 60-80%
        candidates = [
            (p, r) for p, r in all_results
            if r.total_return_pct >= 30.0
            and 60.0 <= r.win_rate_pct <= 80.0
            and r.total_trades >= MIN_TRADES
        ]
        candidates.sort(
            key=lambda x: (x[1].max_drawdown_pct, -x[1].total_trades, -x[1].total_return_pct)
        )
        if candidates:
            log("\n  No combo hit 40% return / 70% WR. Showing best with return>=30%, WR 60-80%:\n")
    if not candidates:
        # Best effort: any positive return, sort by return then DD
        best_any = [(p, r) for p, r in all_results if r.total_trades >= 5]
        best_any.sort(
            key=lambda x: (-x[1].total_return_pct, x[1].max_drawdown_pct, -x[1].win_rate_pct)
        )
        if best_any:
            log("\n  No combo hit 30%+ return. Showing best overall:\n")
            candidates = best_any[:5]

    if not candidates:
        log("No valid results. Try more rounds (--rounds 5) or check data.")
        return 1

    best_params, best_result = candidates[0]
    log("\n" + "=" * 70)
    log("  OPTIMIZED PARAMETERS (target: 40%+ return, ~70% WR, min DD, max trades)")
    log("=" * 70)
    log(f"  MIN_RR_RATIO         = {best_params.get('min_rr')}")
    log(f"  LEVEL_TOLERANCE_PTS  = {best_params.get('level_tol')}")
    log(f"  MAX_RISK_PTS         = {best_params.get('max_risk_pts')}")
    log(f"  MAX_TRADES_PER_DAY   = {best_params.get('max_trades_per_day')}")
    log(f"  SKIP_FIRST_MINUTES   = {best_params.get('skip_first')}")
    log(f"  MIN_BODY_PTS         = {best_params.get('min_body')}")
    log(f"  RETEST_ONLY          = {best_params.get('retest_only')}")
    log(f"  REQUIRE_TREND_ONLY   = {best_params.get('require_trend_only')}")
    log(f"  Risk per trade USD   = {best_params.get('risk')}")
    if best_params.get("max_dd_cap_pct") is not None:
        log(f"  MAX_DRAWDOWN_CAP_PCT = {best_params.get('max_dd_cap_pct')}")
    log("-" * 70)
    log(f"  Total return:    {best_result.total_return_pct:+.2f}%")
    log(f"  Win rate:        {best_result.win_rate_pct:.1f}%")
    log(f"  Total trades:    {best_result.total_trades} (W={best_result.winners} L={best_result.losers})")
    log(f"  Max drawdown:    {best_result.max_drawdown_pct:.2f}% (${best_result.max_drawdown_usd:,.2f})")
    log(f"  Profit factor:   {best_result.profit_factor:.2f}")
    log(f"  Net P&L:        ${best_result.final_balance - best_result.initial_balance:+,.2f}")
    log("=" * 70)

    # Write config snippet to apply
    out_path = ROOT / "optimized_config_snippet.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Paste into config.py or set in .env\n")
        f.write(f"MIN_RR_RATIO = {best_params.get('min_rr')}\n")
        f.write(f"LEVEL_TOLERANCE_PTS = {best_params.get('level_tol')}\n")
        f.write(f"MAX_RISK_PTS = {best_params.get('max_risk_pts')}\n")
        f.write(f"MAX_TRADES_PER_DAY = {best_params.get('max_trades_per_day')}\n")
        f.write(f"SKIP_FIRST_MINUTES = {best_params.get('skip_first')}\n")
        f.write(f"MIN_BODY_PTS = {best_params.get('min_body')}\n")
        f.write(f"RETEST_ONLY = {best_params.get('retest_only')}\n")
        f.write(f"MAX_RISK_PER_TRADE_USD = {best_params.get('risk')}\n")
    log(f"\n  Config snippet saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
