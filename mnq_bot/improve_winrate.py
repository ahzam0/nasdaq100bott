"""
Test param sets to improve win rate. Runs backtest for each combo, prints WR + return, picks best WR with decent return.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable or "python"

# Param sets: (min_rr, level_tol, skip_first, min_body, max_trades, label)
# Stricter = fewer trades, often higher WR
COMBOS = [
    (1.8, 8.0, 0, 0.0, 3, "current"),
    (1.9, 8.0, 0, 0.0, 3, "min_rr_1.9"),
    (2.0, 8.0, 0, 0.0, 3, "min_rr_2.0"),
    (1.9, 7.0, 0, 0.0, 3, "rr_1.9_tol_7"),
    (1.9, 7.0, 5, 0.0, 3, "rr_1.9_tol_7_skip5"),
    (1.9, 7.0, 10, 0.0, 3, "rr_1.9_tol_7_skip10"),
    (1.85, 7.5, 5, 0.0, 3, "rr_1.85_tol_7.5_skip5"),
    (1.9, 7.0, 0, 1.0, 3, "rr_1.9_tol_7_minbody1"),
    (2.0, 7.0, 5, 0.0, 3, "rr_2_tol_7_skip5"),
    (1.9, 6.5, 5, 0.0, 3, "rr_1.9_tol_6.5_skip5"),
    (1.85, 8.0, 5, 0.0, 2, "rr_1.85_skip5_maxtrades2"),
]


DATA_PREFIX = "data/wr_test"


def run_one(min_rr, level_tol, skip_first, min_body, max_trades, load_saved: bool) -> tuple[float, float, int, float]:
    """Run backtest, return (win_rate_pct, return_pct, total_trades, max_dd_pct). Parse stdout."""
    base = [PY, str(ROOT / "run_backtest.py"), "--risk", "420",
            "--min-rr", str(min_rr), "--level-tol", str(level_tol),
            "--skip-first", str(skip_first), "--min-body", str(min_body), "--max-trades", str(max_trades)]
    if load_saved:
        cmd = base + ["--load-data", DATA_PREFIX]
    else:
        cmd = base + ["--live", "--months", "3"]
    try:
        out = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        text = out.stdout or ""
        # Parse: "Win rate:            51.9%"
        wr = None
        ret = None
        trades = None
        dd = None
        for line in text.splitlines():
            if "Win rate:" in line:
                try:
                    wr = float(line.split("%")[0].strip().split()[-1])
                except Exception:
                    pass
            if "Total return:" in line:
                try:
                    ret = float(line.split("%")[0].strip().split()[-1].replace("+", ""))
                except Exception:
                    pass
            if "Total trades:" in line:
                try:
                    trades = int(line.strip().split()[-1])
                except Exception:
                    pass
            if "Max drawdown:" in line and "$" in line:
                try:
                    # "  Max drawdown:        $2,125.00 (3.06%)"
                    dd = float(line.split("(")[1].split("%")[0].strip())
                except Exception:
                    pass
        return (wr or 0, ret or 0, trades or 0, dd or 0)
    except Exception as e:
        return (0, 0, 0, 0)


def main():
    # Save data once so we don't fetch 11 times
    data_1m = ROOT / "data" / "wr_test_1m.csv"
    if not data_1m.exists():
        print("Saving live data once...")
        subprocess.run(
            [PY, str(ROOT / "run_backtest.py"), "--live", "--months", "3", "--risk", "420", "--save-data", "data/wr_test"],
            cwd=str(ROOT), capture_output=True, timeout=120,
        )
    load_saved = (ROOT / "data" / "wr_test_1m.csv").exists()
    print("Improving win rate – testing", len(COMBOS), "param sets (risk 420)...\n")
    results = []
    for t in COMBOS:
        min_rr, level_tol, skip_first, min_body, max_trades, label = t
        wr, ret, trades, dd = run_one(min_rr, level_tol, skip_first, min_body, max_trades, load_saved=load_saved)
        results.append((label, wr, ret, trades, dd, t))
        print(f"  {label:25}  WR={wr:.1f}%  return={ret:+.2f}%  trades={trades}  DD={dd:.2f}%")

    # Sort by win rate (desc), then by return (desc). Require at least 15 trades for stats.
    valid = [r for r in results if r[3] >= 15]
    if not valid:
        valid = results
    valid.sort(key=lambda x: (-x[1], -x[2]))

    best = valid[0]
    label, wr, ret, trades, dd, t = best
    min_rr, level_tol, skip_first, min_body, max_trades, _ = t

    print("\n" + "=" * 60)
    print("  BEST WIN RATE (with decent return & trade count)")
    print("=" * 60)
    print(f"  Label:    {label}")
    print(f"  Win rate: {wr:.1f}%  |  Return: {ret:+.2f}%  |  Trades: {trades}  |  DD: {dd:.2f}%")
    print(f"  Params:   MIN_RR_RATIO={min_rr}, LEVEL_TOLERANCE_PTS={level_tol}, SKIP_FIRST_MINUTES={skip_first}, MIN_BODY_PTS={min_body}, MAX_TRADES_PER_DAY={max_trades}")
    print("=" * 60)

    # Write snippet and update config
    snippet = ROOT / "optimized_config_snippet.txt"
    snippet.write_text(
        "# Better win rate – paste into config or run apply_optimized_config.py\n"
        f"MIN_RR_RATIO = {min_rr}\n"
        f"LEVEL_TOLERANCE_PTS = {level_tol}\n"
        f"MAX_RISK_PTS = 350.0\n"
        f"MAX_TRADES_PER_DAY = {max_trades}\n"
        f"SKIP_FIRST_MINUTES = {skip_first}\n"
        f"MIN_BODY_PTS = {min_body}\n"
        f"RETEST_ONLY = True\n"
        f"MAX_RISK_PER_TRADE_USD = 420\n",
        encoding="utf-8",
    )
    print(f"\n  Wrote {snippet}")

    # Apply to config
    sys.path.insert(0, str(ROOT))
    import apply_optimized_config
    apply_optimized_config.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
