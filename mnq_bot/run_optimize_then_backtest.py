"""
Run optimizer (grid + hill climb) then run live backtest with the best config.
Usage:
  python run_optimize_then_backtest.py              # run optimizer, then live backtest with best
  python run_optimize_then_backtest.py --backtest-only   # skip optimizer, run live backtest with existing best_config.json
  python run_optimize_then_backtest.py --optimize-only    # run optimizer only (saves to data/best_config.json)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BEST_JSON = ROOT / "data" / "best_config.json"


def run_optimizer() -> int:
    """Run optimize_best.py; return exit code."""
    return subprocess.call(
        [sys.executable, "-u", str(ROOT / "optimize_best.py")],
        cwd=str(ROOT),
    )


def run_backtest_with_best(months: int = 3, balance: float = 50000, risk: float = 380) -> int:
    """Load best_config.json and run run_backtest.py --live with those params."""
    if not BEST_JSON.exists():
        print(f"ERROR: {BEST_JSON} not found. Run optimizer first (no --backtest-only).")
        return 1
    raw = json.loads(BEST_JSON.read_text(encoding="utf-8"))
    params = raw.get("params") or raw
    # Build argv for run_backtest.py
    cmd = [
        sys.executable,
        str(ROOT / "run_backtest.py"),
        "--live",
        "--months", str(months),
        "--balance", str(balance),
        "--risk", str(risk),
        "--min-rr", str(params.get("min_rr", 1.8)),
        "--level-tol", str(params.get("level_tolerance_pts", 8.0)),
        "--max-trades", str(int(params.get("max_trades_per_day", 3))),
        "--skip-first", str(int(params.get("skip_first_minutes", 0))),
        "--min-body", str(float(params.get("min_body_pts", 0))),
        "--max-risk-pts", str(float(params.get("max_risk_pts", 350))),
        "--fallback-after", str(int(params.get("fallback_after_min", 90))),
        "--fallback-min-rr", str(float(params.get("fallback_min_rr", 1.5))),
    ]
    if params.get("require_trend_only", True):
        cmd.append("--require-trend-only")
    else:
        cmd.append("--no-require-trend-only")
    if params.get("retest_only", True):
        cmd.append("--retest-only")
    else:
        cmd.append("--no-retest-only")
    print("Running live backtest with best config:", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def main():
    ap = argparse.ArgumentParser(description="Optimize then backtest with best config")
    ap.add_argument("--backtest-only", action="store_true", help="Skip optimizer; run live backtest with existing best_config.json")
    ap.add_argument("--optimize-only", action="store_true", help="Run optimizer only; do not run backtest")
    ap.add_argument("--months", type=int, default=3, help="Months of live data for backtest (default 3)")
    ap.add_argument("--balance", type=float, default=50000, help="Starting balance (default 50000)")
    ap.add_argument("--risk", type=float, default=380, help="Risk per trade USD (default 380)")
    args = ap.parse_args()

    if args.backtest_only:
        return run_backtest_with_best(months=args.months, balance=args.balance, risk=args.risk)
    if args.optimize_only:
        return run_optimizer()
    # Full: optimize then backtest
    code = run_optimizer()
    if code != 0:
        return code
    return run_backtest_with_best(months=args.months, balance=args.balance, risk=args.risk)


if __name__ == "__main__":
    sys.exit(main())
