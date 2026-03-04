"""
Quick optimize: run 6 targeted param sets (doc best + variations), pick best by return, write snippet and apply to config.
Target: maximize return on current 3mo data.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import BacktestEngine
from backtest.live_data import fetch_live_backtest_data
from config import REQUIRE_TREND_ONLY, FALLBACK_AFTER_MINUTES, FALLBACK_MIN_RR, TARGET_MIN_TRADES_PER_DAY

# 6 param sets: doc best + variations that often help return
PARAM_SETS = [
    {"risk": 380, "min_rr": 1.8, "level_tol": 8.0, "max_risk_pts": 350.0, "skip_first": 0, "retest_only": True},
    {"risk": 380, "min_rr": 1.9, "level_tol": 8.0, "max_risk_pts": 350.0, "skip_first": 0, "retest_only": True},
    {"risk": 380, "min_rr": 1.8, "level_tol": 7.0, "max_risk_pts": 350.0, "skip_first": 0, "retest_only": True},
    {"risk": 400, "min_rr": 1.8, "level_tol": 8.0, "max_risk_pts": 350.0, "skip_first": 0, "retest_only": True},
    {"risk": 380, "min_rr": 1.75, "level_tol": 8.0, "max_risk_pts": 350.0, "skip_first": 0, "retest_only": True},
    {"risk": 380, "min_rr": 1.8, "level_tol": 8.0, "max_risk_pts": 300.0, "skip_first": 5, "retest_only": True},
]


def main():
    print("Fetching data...")
    df_1m, df_15m = fetch_live_backtest_data(months=3)
    if df_1m.empty or len(df_1m) < 500:
        print("ERROR: Not enough data.")
        return 1
    print(f"  1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}\n")

    results = []
    for i, p in enumerate(PARAM_SETS):
        engine = BacktestEngine(
            initial_balance=50_000,
            risk_per_trade_usd=p["risk"],
            max_trades_per_day=3,
            min_rr=p["min_rr"],
            level_tolerance_pts=p["level_tol"],
            require_trend_only=REQUIRE_TREND_ONLY,
            skip_first_minutes=p["skip_first"],
            retest_only=p["retest_only"],
            min_body_pts=0.0,
            max_drawdown_cap_pct=None,
            max_risk_pts=p["max_risk_pts"],
            fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
            fallback_min_rr=FALLBACK_MIN_RR if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
            use_orderflow_proxy=False,
        )
        r = engine.run(df_1m, df_15m)
        results.append((p, r))
        print(f"  {i+1}/6  return={r.total_return_pct:+.2f}%  WR={r.win_rate_pct:.1f}%  trades={r.total_trades}")

    # Best by return (min 5 trades)
    valid = [(p, r) for p, r in results if r.total_trades >= 5]
    if not valid:
        valid = results
    best_params, best_result = max(valid, key=lambda x: x[1].total_return_pct)

    print(f"\nBest: return={best_result.total_return_pct:+.2f}%  WR={best_result.win_rate_pct:.1f}%  trades={best_result.total_trades}")

    snippet_path = ROOT / "optimized_config_snippet.txt"
    snippet_path.write_text(
        "# Paste into config.py or set in .env\n"
        f"MIN_RR_RATIO = {best_params['min_rr']}\n"
        f"LEVEL_TOLERANCE_PTS = {best_params['level_tol']}\n"
        f"MAX_RISK_PTS = {best_params['max_risk_pts']}\n"
        f"MAX_TRADES_PER_DAY = 3\n"
        f"SKIP_FIRST_MINUTES = {best_params['skip_first']}\n"
        f"MIN_BODY_PTS = 0.0\n"
        f"RETEST_ONLY = {best_params['retest_only']}\n"
        f"MAX_RISK_PER_TRADE_USD = {best_params['risk']}\n",
        encoding="utf-8",
    )
    print(f"Wrote {snippet_path}")

    # Apply to config
    import apply_optimized_config
    apply_optimized_config.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
