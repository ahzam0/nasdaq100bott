"""
BEST IN THE WORLD – one composite score, maximum search, auto-apply to config.
Finds the single best parameter set on your data (return + win rate + low DD + profit factor).
Run: python optimize_best.py [--workers 8] [--rounds 8] [--combos 100]
"""

from __future__ import annotations

import math
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
MIN_TRADES = 5  # Need enough for stats


def score_world_class(r: BacktestResult) -> float:
    """
    Single number: higher = better. Best in the world = max this.
    We want: high return, high win rate, low drawdown, high profit factor, enough trades.
    """
    ret = r.total_return_pct / 100.0          # e.g. 0.32
    wr = r.win_rate_pct / 100.0               # e.g. 0.31
    dd = r.max_drawdown_pct / 100.0           # e.g. 0.0789
    pf = min(r.profit_factor, 10.0)           # cap
    n = min(r.total_trades, 80)
    # Weights: return and win rate matter most, then punish DD, then PF and trades
    return (
        ret * 2.0 +           # return primary
        wr * 1.5 -             # win rate
        dd * 2.0 +             # punish drawdown
        math.log1p(pf) * 1.0 +  # profit factor
        (n / 80) * 0.3         # slight bonus for more trades (statistical confidence)
    )


def run_one(params: dict, df_1m, df_15m) -> tuple[dict, BacktestResult]:
    engine = BacktestEngine(
        initial_balance=params.get("balance", BALANCE),
        risk_per_trade_usd=params.get("risk", 330),
        max_trades_per_day=params.get("max_trades_per_day", 3),
        min_rr=params.get("min_rr", 1.75),
        level_tolerance_pts=params.get("level_tol", 6.0),
        require_trend_only=params.get("require_trend_only", REQUIRE_TREND_ONLY),
        skip_first_minutes=params.get("skip_first", 0),
        retest_only=params.get("retest_only", True),
        min_body_pts=params.get("min_body", 0.0),
        max_drawdown_cap_pct=params.get("max_dd_cap_pct"),
        max_risk_pts=params.get("max_risk_pts", 350.0),
        fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
        fallback_min_rr=params.get("fallback_min_rr", FALLBACK_MIN_RR) if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
        use_orderflow_proxy=params.get("use_orderflow_proxy", False),
    )
    return (params, engine.run(df_1m, df_15m))


def run_chunk(args):
    chunk_params, df_1m, df_15m = args
    out = []
    for p in chunk_params:
        try:
            out.append(run_one(p, df_1m, df_15m))
        except Exception:
            pass
    return out


def generate_best_params(n: int, seed: int) -> list[dict]:
    """Wide range: strict (high WR) + loose (high return) + middle."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        # Mix: 40% strict, 40% medium, 20% loose
        roll = rng.random()
        if roll < 0.4:
            min_rr = round(rng.uniform(2.0, 2.8), 2)
            level_tol = round(rng.uniform(4.0, 7.0), 1)
            max_risk_pts = round(rng.uniform(100, 200), 0)
            retest_only = True
            skip_first = rng.randint(8, 20)
        elif roll < 0.8:
            min_rr = round(rng.uniform(1.7, 2.2), 2)
            level_tol = round(rng.uniform(6.0, 9.0), 1)
            max_risk_pts = round(rng.uniform(150, 300), 0)
            retest_only = rng.choice([True, False])
            skip_first = rng.randint(0, 15)
        else:
            min_rr = round(rng.uniform(1.5, 2.0), 2)
            level_tol = round(rng.uniform(7.0, 10.0), 1)
            max_risk_pts = round(rng.uniform(200, 380), 0)
            retest_only = rng.choice([True, False])
            skip_first = rng.randint(0, 10)
        p = {
            "risk": round(rng.uniform(300, 400), 0),
            "min_rr": min_rr,
            "level_tol": level_tol,
            "max_risk_pts": max_risk_pts if max_risk_pts >= 80 else 120,
            "max_trades_per_day": rng.randint(2, 4),
            "skip_first": skip_first,
            "min_body": round(rng.uniform(0, 3.0), 1) if rng.random() > 0.6 else 0.0,
            "retest_only": retest_only,
            "require_trend_only": rng.choice([True, True, False]),
            "max_dd_cap_pct": round(rng.uniform(4, 9), 1) if rng.random() > 0.5 else None,
            "fallback_min_rr": round(rng.uniform(1.6, 2.0), 2),
        }
        out.append(p)
    return out


def apply_to_config(best_params: dict, config_path: Path) -> None:
    """Write best params into config.py so bot uses them."""
    lines = config_path.read_text(encoding="utf-8").splitlines()
    key_to_value = {
        "MIN_RR_RATIO": best_params.get("min_rr"),
        "LEVEL_TOLERANCE_PTS": best_params.get("level_tol"),
        "MAX_RISK_PTS": best_params.get("max_risk_pts"),
        "MAX_TRADES_PER_DAY": best_params.get("max_trades_per_day"),
        "SKIP_FIRST_MINUTES": best_params.get("skip_first"),
        "MIN_BODY_PTS": best_params.get("min_body"),
        "RETEST_ONLY": best_params.get("retest_only"),
        "MAX_RISK_PER_TRADE_USD": best_params.get("risk"),
    }
    new_lines = []
    for line in lines:
        updated = False
        for key, value in key_to_value.items():
            if value is None:
                continue
            if line.lstrip().startswith(key + " ") or line.lstrip().startswith(key + "="):
                if isinstance(value, bool):
                    s = "True" if value else "False"
                else:
                    s = str(value)
                idx = line.find("=")
                new_lines.append(line[: idx + 1] + " " + s)
                updated = True
                break
        if not updated:
            new_lines.append(line)
    config_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Best in the world – max score, auto-apply to config")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=8)
    parser.add_argument("--combos", type=int, default=100)
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--seed", type=int, default=999)
    parser.add_argument("--no-apply", action="store_true", help="Do not write config.py")
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
    total = args.rounds * args.combos
    log(f"Running {total} backtests (rounds={args.rounds}, combos={args.combos}, workers={args.workers})...\n")

    for round_num in range(1, args.rounds + 1):
        params_list = generate_best_params(args.combos, seed=args.seed + round_num * 1000)
        if args.workers <= 1:
            for i, p in enumerate(params_list):
                try:
                    all_results.append(run_one(p, df_1m, df_15m))
                except Exception:
                    pass
                if (i + 1) % 25 == 0:
                    log(f"  Round {round_num}: {i + 1}/{len(params_list)} done...")
        else:
            from concurrent.futures import ProcessPoolExecutor, as_completed
            chunk_size = max(1, len(params_list) // args.workers)
            chunks = [params_list[i:i + chunk_size] for i in range(0, len(params_list), chunk_size)]
            chunk_args = [(c, df_1m, df_15m) for c in chunks]
            with ProcessPoolExecutor(max_workers=args.workers) as ex:
                for fut in as_completed([ex.submit(run_chunk, a) for a in chunk_args]):
                    try:
                        for item in fut.result():
                            all_results.append(item)
                    except Exception as e:
                        log(f"  Worker error: {e}")
            log(f"  Round {round_num} done. Total so far: {len(all_results)}")

    # Keep only with enough trades, then pick BEST by world-class score
    valid = [(p, r) for p, r in all_results if r.total_trades >= MIN_TRADES]
    if not valid:
        valid = all_results
    valid.sort(key=lambda x: score_world_class(x[1]), reverse=True)
    best_params, best_result = valid[0]

    log("\n" + "=" * 70)
    log("  BEST IN THE WORLD (on this data)")
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
    if best_params.get("max_dd_cap_pct"):
        log(f"  MAX_DD_CAP_PCT       = {best_params.get('max_dd_cap_pct')}")
    log("-" * 70)
    log(f"  Total return:    {best_result.total_return_pct:+.2f}%")
    log(f"  Win rate:        {best_result.win_rate_pct:.1f}%")
    log(f"  Max drawdown:    {best_result.max_drawdown_pct:.2f}% (${best_result.max_drawdown_usd:,.2f})")
    log(f"  Profit factor:   {best_result.profit_factor:.2f}")
    log(f"  Total trades:    {best_result.total_trades} (W={best_result.winners} L={best_result.losers})")
    log(f"  Net P&L:         ${best_result.final_balance - best_result.initial_balance:+,.2f}")
    log(f"  World-class score: {score_world_class(best_result):.3f}")
    log("=" * 70)

    snippet_path = ROOT / "optimized_config_snippet.txt"
    with open(snippet_path, "w", encoding="utf-8") as f:
        f.write("# Best in the world – paste into config.py or .env\n")
        f.write(f"MIN_RR_RATIO = {best_params.get('min_rr')}\n")
        f.write(f"LEVEL_TOLERANCE_PTS = {best_params.get('level_tol')}\n")
        f.write(f"MAX_RISK_PTS = {best_params.get('max_risk_pts')}\n")
        f.write(f"MAX_TRADES_PER_DAY = {best_params.get('max_trades_per_day')}\n")
        f.write(f"SKIP_FIRST_MINUTES = {best_params.get('skip_first')}\n")
        f.write(f"MIN_BODY_PTS = {best_params.get('min_body')}\n")
        f.write(f"RETEST_ONLY = {best_params.get('retest_only')}\n")
        f.write(f"MAX_RISK_PER_TRADE_USD = {best_params.get('risk')}\n")
    log(f"\n  Snippet saved to {snippet_path}")

    if not args.no_apply:
        config_path = ROOT / "config.py"
        try:
            apply_to_config(best_params, config_path)
            log(f"  Config updated: {config_path}")
        except Exception as e:
            log(f"  Could not auto-apply config: {e}. Paste from snippet manually.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
