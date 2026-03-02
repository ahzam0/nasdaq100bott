"""
Train the MNQ strategy for live market: optimize on recent data with train/validation split.
- Fetches 3 months of live data (Yahoo NQ=F).
- Train period: first ~2 months. Validation period: last ~1 month (most recent = "live-like").
- Sweeps key parameters on TRAIN; picks best by combined score (profit, win rate, low DD).
- Re-evaluates top configs on VALIDATION to choose the one that generalizes.
- Updates config.py with the best parameters and writes TRAIN_LIVE_RESULT.md.

Run: python train_for_live.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from config import (
    MAX_TRADES_PER_DAY,
    REQUIRE_TREND_ONLY,
    FALLBACK_AFTER_MINUTES,
    FALLBACK_MIN_RR,
    TARGET_MIN_TRADES_PER_DAY,
)
from backtest import BacktestEngine, BacktestResult
from backtest.live_data import fetch_live_backtest_data

EST = ZoneInfo("America/New_York")
BALANCE = 50_000.0
RISK_DEFAULT = 370
MAX_DD_CAP_PCT = 10.0  # Ignore configs with DD above this on train


def split_train_val(
    df_1m: pd.DataFrame, df_15m: pd.DataFrame, val_days: int = 30
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split into train (all before last val_days) and validation (last val_days)."""
    if df_1m.empty:
        return df_1m, df_15m, pd.DataFrame(), pd.DataFrame()
    idx = df_1m.index
    if idx.tzinfo is None:
        idx = idx.tz_localize(EST, ambiguous="infer")
    else:
        idx = idx.tz_convert(EST)
    cutoff = idx.max() - timedelta(days=val_days)
    train_1m = df_1m.loc[df_1m.index <= cutoff].copy()
    val_1m = df_1m.loc[df_1m.index > cutoff].copy()
    if df_15m.empty:
        return train_1m, df_15m, val_1m, pd.DataFrame()
    idx15 = df_15m.index
    if idx15.tzinfo is None:
        idx15 = idx15.tz_localize(EST, ambiguous="infer")
    else:
        idx15 = idx15.tz_convert(EST)
    cutoff15 = idx15.max() - timedelta(days=val_days)
    train_15m = df_15m.loc[df_15m.index <= cutoff15].copy()
    val_15m = df_15m.loc[df_15m.index > cutoff15].copy()
    return train_1m, train_15m, val_1m, val_15m


def run_backtest(
    df_1m: pd.DataFrame,
    df_15m: pd.DataFrame,
    risk: float,
    min_rr: float,
    level_tol: float,
    max_risk_pts: float | None,
    skip_first: int,
    retest_only: bool,
    min_body: float,
) -> BacktestResult:
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
        max_risk_pts=max_risk_pts,
        fallback_after_minutes=FALLBACK_AFTER_MINUTES if TARGET_MIN_TRADES_PER_DAY >= 1 else 0,
        fallback_min_rr=FALLBACK_MIN_RR if TARGET_MIN_TRADES_PER_DAY >= 1 else None,
    )
    return engine.run(df_1m, df_15m)


def score_for_live(r: BacktestResult) -> float:
    """Higher is better for live: profit, win rate, profit factor; penalize DD."""
    if r.total_trades < 5:
        return -999_999.0
    profit = r.final_balance - r.initial_balance
    dd_pct = r.max_drawdown_pct / 100.0
    wr = r.win_rate_pct / 100.0
    pf = min(r.profit_factor, 6.0)
    # Emphasize profit and robustness; cap DD penalty
    return profit * 0.5 - (dd_pct * BALANCE * 0.3) + wr * 500 + pf * 50


def run_auto_retrain(
    update_config: bool = True,
    verbose: bool = True,
) -> dict:
    """
    Run full training on live data and optionally update config.py.
    Call from app scheduler (verbose=False) or CLI (verbose=True).
    Returns dict: success, error, best_params, full_profit, total_return_pct, total_trades, win_rate_pct, max_drawdown_pct.
    """
    import re
    result = {
        "success": False,
        "error": None,
        "best_params": None,
        "full_profit": 0.0,
        "total_return_pct": 0.0,
        "total_trades": 0,
        "win_rate_pct": 0.0,
        "max_drawdown_pct": 0.0,
    }
    def log(msg: str) -> None:
        if verbose:
            print(msg)

    log("=" * 60)
    log("  MNQ STRATEGY – TRAIN FOR LIVE MARKET")
    log("=" * 60)
    log("\nFetching 3 months of live data (Yahoo NQ=F, 7-11 EST)...")
    try:
        df_1m, df_15m = fetch_live_backtest_data(months=3)
    except Exception as e:
        result["error"] = str(e)
        log(f"ERROR: {e}")
        return result
    if df_1m.empty or len(df_1m) < 500:
        result["error"] = "Not enough data."
        log("ERROR: Not enough data.")
        return result
    log(f"  Total 1m bars: {len(df_1m)}, 15m bars: {len(df_15m)}")

    train_1m, train_15m, val_1m, val_15m = split_train_val(df_1m, df_15m, val_days=30)
    log(f"  Train: {len(train_1m)} 1m bars, {len(train_15m)} 15m bars")
    log(f"  Validation (last 30 days): {len(val_1m)} 1m bars, {len(val_15m)} 15m bars\n")

    # Parameter grid tuned for live: balance profit vs stability
    param_grid = [
        # (risk, min_rr, level_tol, max_risk_pts, skip_first, retest_only, min_body)
        (370, 1.8, 6.0, 350.0, 0, True, 0.0),
        (370, 1.7, 6.0, 350.0, 0, True, 0.0),
        (370, 1.8, 8.0, 350.0, 0, True, 0.0),
        (360, 1.8, 6.0, 350.0, 0, True, 0.0),
        (380, 1.8, 6.0, 350.0, 0, True, 0.0),
        (370, 1.8, 6.0, 400.0, 0, True, 0.0),
        (370, 1.8, 6.0, 300.0, 0, True, 0.0),
        (370, 1.85, 6.0, 350.0, 0, True, 0.0),
        (370, 1.8, 6.0, 350.0, 5, True, 0.0),
        (370, 1.8, 6.0, 350.0, 0, False, 0.0),
        (370, 1.75, 7.0, 350.0, 0, True, 0.0),
    ]

    train_results = []
    for risk, min_rr, level_tol, max_rp, skip_first, retest_only, min_body in param_grid:
        try:
            r = run_backtest(
                train_1m, train_15m,
                risk=risk, min_rr=min_rr, level_tol=level_tol, max_risk_pts=max_rp,
                skip_first=skip_first, retest_only=retest_only, min_body=min_body,
            )
        except Exception as e:
            log(f"  FAIL: risk={risk} min_rr={min_rr} tol={level_tol} max_rp={max_rp} -> {e}")
            continue
        if r.max_drawdown_pct > MAX_DD_CAP_PCT:
            continue
        scr = score_for_live(r)
        train_results.append((
            scr,
            r.final_balance - r.initial_balance,
            r.max_drawdown_pct,
            r.total_trades,
            r.win_rate_pct,
            (risk, min_rr, level_tol, max_rp, skip_first, retest_only, min_body),
        ))
        log(
            f"  Train: risk={risk} min_rr={min_rr} tol={level_tol} max_rp={max_rp} "
            f"-> P&L=${r.final_balance - r.initial_balance:+,.0f} DD={r.max_drawdown_pct:.2f}% trades={r.total_trades} WR={r.win_rate_pct:.1f}% score={scr:.1f}"
        )

    if not train_results:
        result["error"] = "No valid train results."
        log("\nNo valid train results.")
        return result

    # Sort by train score descending; take top 5 and evaluate on validation
    train_results.sort(key=lambda x: x[0], reverse=True)
    top_n = min(5, len(train_results))
    log(f"\nTop {top_n} configs on train; evaluating on validation (last 30 days)...")

    best_val_profit = -999_999.0
    best_params = None
    best_val_result = None

    for i in range(top_n):
        _, _, _, _, _, params = train_results[i]
        risk, min_rr, level_tol, max_rp, skip_first, retest_only, min_body = params
        if val_1m.empty or len(val_1m) < 100:
            break
        try:
            r_val = run_backtest(
                val_1m, val_15m,
                risk=risk, min_rr=min_rr, level_tol=level_tol, max_risk_pts=max_rp,
                skip_first=skip_first, retest_only=retest_only, min_body=min_body,
            )
        except Exception as e:
            log(f"  Val FAIL for {params}: {e}")
            continue
        val_profit = r_val.final_balance - r_val.initial_balance
        log(
            f"  Val: risk={risk} min_rr={min_rr} tol={level_tol} max_rp={max_rp} "
            f"-> P&L=${val_profit:+,.0f} DD={r_val.max_drawdown_pct:.2f}% trades={r_val.total_trades}"
        )
        if val_profit > best_val_profit:
            best_val_profit = val_profit
            best_params = params
            best_val_result = r_val

    if best_params is None:
        # No validation data or all failed: use best by train score
        best_params = train_results[0][5]
        risk, min_rr, level_tol, max_rp, skip_first, retest_only, min_body = best_params
        best_val_result = run_backtest(
            train_1m, train_15m,
            risk=risk, min_rr=min_rr, level_tol=level_tol, max_risk_pts=max_rp,
            skip_first=skip_first, retest_only=retest_only, min_body=min_body,
        )
        log("\nValidation skipped (insufficient data); using best train config.")

    risk, min_rr, level_tol, max_rp, skip_first, retest_only, min_body = best_params

    # Full 3-month run with best params for report
    log("\nRunning full 3-month backtest with best config...")
    r_full = run_backtest(
        df_1m, df_15m,
        risk=risk, min_rr=min_rr, level_tol=level_tol, max_risk_pts=max_rp,
        skip_first=skip_first, retest_only=retest_only, min_body=min_body,
    )
    full_profit = r_full.final_balance - r_full.initial_balance

    result["success"] = True
    result["best_params"] = {"risk": risk, "min_rr": min_rr, "level_tol": level_tol, "max_rp": max_rp, "skip_first": skip_first, "retest_only": retest_only, "min_body": min_body}
    result["full_profit"] = full_profit
    result["total_return_pct"] = r_full.total_return_pct
    result["total_trades"] = r_full.total_trades
    result["win_rate_pct"] = r_full.win_rate_pct
    result["max_drawdown_pct"] = r_full.max_drawdown_pct

    log("\n" + "=" * 60)
    log("  BEST CONFIG FOR LIVE MARKET")
    log("=" * 60)
    log(f"  MAX_RISK_PER_TRADE_USD = {risk}")
    log(f"  MIN_RR_RATIO = {min_rr}")
    log(f"  LEVEL_TOLERANCE_PTS = {level_tol}")
    log(f"  MAX_RISK_PTS = {max_rp}")
    log(f"  SKIP_FIRST_MINUTES = {skip_first}")
    log(f"  RETEST_ONLY = {retest_only}")
    log(f"  MIN_BODY_PTS = {min_body}")
    log(f"  Full 3mo: P&L=${full_profit:+,.2f} ({r_full.total_return_pct:+.2f}%) | Trades={r_full.total_trades} | WR={r_full.win_rate_pct:.1f}% | DD={r_full.max_drawdown_pct:.2f}%")
    log("=" * 60)

    if not update_config:
        return result

    # Update config.py
    config_path = ROOT / "config.py"
    config_text = config_path.read_text(encoding="utf-8")

    def replace_config(name: str, value: str | int | float | bool) -> None:
        nonlocal config_text
        if isinstance(value, bool):
            value = "True" if value else "False"
        elif isinstance(value, float):
            value = str(value)
        # Match lines like MIN_RR_RATIO = 1.8 or MAX_RISK_PTS = 350.0
        import re
        pattern = rf"^(\s*{re.escape(name)}\s*=\s*)[^\n]+"
        replacement = rf"\g<1>{value}"
        config_text = re.sub(pattern, replacement, config_text, flags=re.MULTILINE)

    replace_config("MAX_RISK_PER_TRADE_USD", int(risk))
    replace_config("MIN_RR_RATIO", min_rr)
    replace_config("LEVEL_TOLERANCE_PTS", level_tol)
    replace_config("MAX_RISK_PTS", max_rp)
    replace_config("SKIP_FIRST_MINUTES", int(skip_first))
    replace_config("RETEST_ONLY", retest_only)
    replace_config("MIN_BODY_PTS", min_body)

    config_path.write_text(config_text, encoding="utf-8")
    log(f"\nUpdated {config_path}")

    # Write TRAIN_LIVE_RESULT.md
    doc = f"""# Strategy Trained for Live Market

**Trained:** {datetime.now(EST).strftime("%Y-%m-%d %H:%M")} EST  
**Data:** Yahoo NQ=F, 3 months, 7-11 EST. Train = first ~2 months, Validation = last 30 days.

## Best parameters (applied to config.py)

| Parameter | Value |
|-----------|--------|
| MAX_RISK_PER_TRADE_USD | {risk} |
| MIN_RR_RATIO | {min_rr} |
| LEVEL_TOLERANCE_PTS | {level_tol} |
| MAX_RISK_PTS | {max_rp} |
| SKIP_FIRST_MINUTES | {skip_first} |
| RETEST_ONLY | {retest_only} |
| MIN_BODY_PTS | {min_body} |

## Full 3-month backtest (best config)

| Metric | Result |
|--------|--------|
| Net P&L | ${full_profit:+,.2f} ({r_full.total_return_pct:+.2f}%) |
| Trades | {r_full.total_trades} (W={r_full.winners} L={r_full.losers}) |
| Win rate | {r_full.win_rate_pct:.1f}% |
| Max drawdown | ${r_full.max_drawdown_usd:,.2f} ({r_full.max_drawdown_pct:.2f}%) |
| Profit factor | {r_full.profit_factor:.2f} |

## Live-market checklist

- [x] Parameters optimized on recent live data with train/validation split
- [ ] Run backtest before each session: `python run_backtest.py --live --months 1`
- [ ] USE_LIVE_FEED = True in config (or env MNQ_USE_LIVE_FEED=true)
- [ ] Telegram credentials set for alerts
- [ ] Start bot during session: `python main.py`
- [ ] Optional: run Price API for lower latency: `python -m api.price_server`
"""
    result_path = ROOT / "TRAIN_LIVE_RESULT.md"
    result_path.write_text(doc, encoding="utf-8")
    log(f"Wrote {result_path}")

    return result


def main():
    res = run_auto_retrain(update_config=True, verbose=True)
    return 0 if res.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
