"""
Optimize for MINIMUM 70% win rate + LOWER drawdown (max parallel "quantum-style" search).
Uses strict entry filters: high min_rr, retest_only, tight stops, skip chop.
Run: python optimize_70wr.py [--workers 8] [--rounds 4] [--combos 80]
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
    FALLBACK_AFTER_MINUTES,
    FALLBACK_MIN_RR,
    TARGET_MIN_TRADES_PER_DAY,
)

BALANCE = 50_000.0
TARGET_WR_MIN = 70.0   # Minimum 70% win rate
MIN_TRADES = 8         # Need enough trades for meaningful WR
MAX_DD_PCT_HARD = 10.0 # Ignore combos with DD above this


def run_one_backtest(params: dict, df_1m, df_15m) -> tuple[dict, BacktestResult]:
    """Run a single backtest. Returns (params, result)."""
    engine = BacktestEngine(
        initial_balance=params.get("balance", BALANCE),
        risk_per_trade_usd=params.get("risk", 330),
        max_trades_per_day=params.get("max_trades_per_day", 3),
        min_rr=params.get("min_rr", 2.0),
        level_tolerance_pts=params.get("level_tol", 5.0),
        require_trend_only=params.get("require_trend_only", True),
        skip_first_minutes=params.get("skip_first", 15),
        retest_only=params.get("retest_only", True),
        min_body_pts=params.get("min_body", 0.0),
        max_drawdown_cap_pct=params.get("max_dd_cap_pct"),
        max_risk_pts=params.get("max_risk_pts", 200.0),
        fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
        fallback_min_rr=params.get("fallback_min_rr", FALLBACK_MIN_RR) if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
        use_orderflow_proxy=params.get("use_orderflow_proxy", False),
    )
    result = engine.run(df_1m, df_15m)
    return (params, result)


def run_chunk(args):
    """Worker: run chunk of param sets. Returns list of (params, result)."""
    chunk_params, df_1m, df_15m = args
    out = []
    for p in chunk_params:
        try:
            out.append(run_one_backtest(p, df_1m, df_15m))
        except Exception:
            pass
    return out


def generate_params_70wr(n: int, seed: int) -> list[dict]:
    """Strict params for high win rate + low DD: high min_rr, retest_only, tight stops, skip chop."""
    rng = random.Random(seed)
    params_list = []
    for _ in range(n):
        p = {
            "risk": round(rng.uniform(280, 380), 0),
            "min_rr": round(rng.uniform(1.85, 2.8), 2),          # Strict R:R (slightly lower for more trades)
            "level_tol": round(rng.uniform(4.0, 8.0), 1),        # Tighter levels
            "max_risk_pts": round(rng.uniform(100, 220), 0),     # Tighter stops, allow some room for trades
            "max_trades_per_day": rng.choice([2, 3]),
            "skip_first": rng.randint(8, 22) if rng.random() > 0.2 else rng.randint(5, 15),
            "min_body": round(rng.uniform(0, 2.5), 1) if rng.random() > 0.5 else 0.0,
            "retest_only": True,
            "require_trend_only": True,
            "max_dd_cap_pct": round(rng.uniform(4, 8), 1) if rng.random() > 0.4 else None,
            "fallback_min_rr": round(rng.uniform(1.7, 2.2), 2),
        }
        if p["max_risk_pts"] < 80:
            p["max_risk_pts"] = 100
        params_list.append(p)
    return params_list


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Optimize for 70%+ WR, lower drawdown (max parallel)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers (default 8). Use 1 for single process.")
    parser.add_argument("--rounds", type=int, default=4, help="Rounds of optimization")
    parser.add_argument("--combos", type=int, default=80, help="Combos per round")
    parser.add_argument("--months", type=int, default=3, help="Months of data")
    parser.add_argument("--seed", type=int, default=123, help="Random seed")
    args = parser.parse_args()

    def log(msg):
        print(msg)
        sys.stdout.flush()

    log("Fetching data (Yahoo NQ=F)...")
    df_1m, df_15m = fetch_live_backtest_data(months=args.months)
    if df_1m.empty or len(df_1m) < 500:
        log("ERROR: Not enough data.")
        return 1
    log(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}\n")

    all_results = []
    for round_num in range(1, args.rounds + 1):
        params_list = generate_params_70wr(args.combos, seed=args.seed + round_num * 1000)

        if args.workers <= 1:
            log(f"Round {round_num}: {len(params_list)} backtests (single process)...")
            for i, p in enumerate(params_list):
                try:
                    all_results.append(run_one_backtest(p, df_1m, df_15m))
                except Exception:
                    pass
                if (i + 1) % 25 == 0:
                    log(f"  {i + 1}/{len(params_list)} done...")
        else:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            chunk_size = max(1, len(params_list) // args.workers)
            chunks = [params_list[i:i + chunk_size] for i in range(0, len(params_list), chunk_size)]
            chunk_args = [(c, df_1m, df_15m) for c in chunks]
            log(f"Round {round_num}: {len(params_list)} backtests ({args.workers} workers)...")
            with ProcessPoolExecutor(max_workers=args.workers) as ex:
                for fut in as_completed([ex.submit(run_chunk, a) for a in chunk_args]):
                    try:
                        for item in fut.result():
                            all_results.append(item)
                    except Exception as e:
                        log(f"  Worker error: {e}")

    # Must have 70%+ WR, then minimize DD, then maximize return
    candidates = [
        (p, r) for p, r in all_results
        if r.win_rate_pct >= TARGET_WR_MIN
        and r.total_trades >= MIN_TRADES
        and r.max_drawdown_pct <= MAX_DD_PCT_HARD
    ]
    candidates.sort(key=lambda x: (x[1].max_drawdown_pct, -x[1].total_return_pct, -x[1].total_trades))

    if not candidates:
        # Relax: WR >= 65%
        candidates = [
            (p, r) for p, r in all_results
            if r.win_rate_pct >= 65.0 and r.total_trades >= MIN_TRADES and r.max_drawdown_pct <= 12.0
        ]
        candidates.sort(key=lambda x: (x[1].max_drawdown_pct, -x[1].win_rate_pct, -x[1].total_return_pct))
        if candidates:
            log("\n  No combo hit 70% WR. Best with WR>=65%, lowest DD:\n")

    if not candidates:
        # Best by WR then DD (always show best achievable)
        best_any = [(p, r) for p, r in all_results if r.total_trades >= 3]
        best_any.sort(key=lambda x: (-x[1].win_rate_pct, x[1].max_drawdown_pct, -x[1].total_return_pct))
        if best_any:
            log("\n  No combo hit 70% WR on this data. Best win rate + lowest DD:\n")
            candidates = best_any[:5]
        else:
            # Last resort: any result, sort by WR
            all_results.sort(key=lambda x: (-x[1].win_rate_pct, x[1].max_drawdown_pct))
            candidates = all_results[:5] if all_results else []
            if candidates:
                log("\n  Best available (few trades):\n")

    if not candidates:
        log("No valid results. Try --rounds 6 --combos 100 or different data.")
        return 1

    best_params, best_result = candidates[0]
    log("\n" + "=" * 70)
    log("  OPTIMIZED FOR 70%+ WIN RATE + LOWER DRAWDOWN")
    log("=" * 70)
    log(f"  MIN_RR_RATIO         = {best_params.get('min_rr')}")
    log(f"  LEVEL_TOLERANCE_PTS  = {best_params.get('level_tol')}")
    log(f"  MAX_RISK_PTS         = {best_params.get('max_risk_pts')}")
    log(f"  MAX_TRADES_PER_DAY   = {best_params.get('max_trades_per_day')}")
    log(f"  SKIP_FIRST_MINUTES   = {best_params.get('skip_first')}")
    log(f"  MIN_BODY_PTS         = {best_params.get('min_body')}")
    log(f"  RETEST_ONLY          = {best_params.get('retest_only')}")
    log(f"  Risk per trade USD   = {best_params.get('risk')}")
    if best_params.get("max_dd_cap_pct") is not None:
        log(f"  MAX_DRAWDOWN_CAP_PCT = {best_params.get('max_dd_cap_pct')}")
    log("-" * 70)
    log(f"  Win rate:        {best_result.win_rate_pct:.1f}%")
    log(f"  Max drawdown:    {best_result.max_drawdown_pct:.2f}% (${best_result.max_drawdown_usd:,.2f})")
    log(f"  Total return:    {best_result.total_return_pct:+.2f}%")
    log(f"  Total trades:    {best_result.total_trades} (W={best_result.winners} L={best_result.losers})")
    log(f"  Profit factor:   {best_result.profit_factor:.2f}")
    log(f"  Net P&L:         ${best_result.final_balance - best_result.initial_balance:+,.2f}")
    log("=" * 70)

    out_path = ROOT / "optimized_config_snippet.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# 70% WR + low DD – paste into config.py or .env\n")
        f.write(f"MIN_RR_RATIO = {best_params.get('min_rr')}\n")
        f.write(f"LEVEL_TOLERANCE_PTS = {best_params.get('level_tol')}\n")
        f.write(f"MAX_RISK_PTS = {best_params.get('max_risk_pts')}\n")
        f.write(f"MAX_TRADES_PER_DAY = {best_params.get('max_trades_per_day')}\n")
        f.write(f"SKIP_FIRST_MINUTES = {best_params.get('skip_first')}\n")
        f.write(f"MIN_BODY_PTS = {best_params.get('min_body')}\n")
        f.write(f"RETEST_ONLY = {best_params.get('retest_only')}\n")
        f.write(f"MAX_RISK_PER_TRADE_USD = {best_params.get('risk')}\n")
        if best_params.get("max_dd_cap_pct") is not None:
            f.write(f"# MAX_DRAWDOWN_CAP_PCT = {best_params.get('max_dd_cap_pct')} (add to backtest args)\n")
    log(f"\n  Config snippet saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
