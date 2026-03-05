"""
Smart Grid + Hill-Climb Optimizer for Riley Coleman MNQ Strategy
Maximizes composite score: PnL + WinRate + ProfitFactor - Drawdown
Enforces >= 1 trade/day. Saves best config and results to data/
"""
from __future__ import annotations

import sys
import logging
import itertools
import json
import csv
import random
from pathlib import Path
from dataclasses import dataclass, asdict

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.disable(logging.CRITICAL)

from backtest import BacktestEngine, generate_backtest_data

# ── Fixed ──────────────────────────────────────────────────────────────────
BALANCE = 50_000.0
RISK = 380.0
DAYS = 60
SEED = 42
MIN_TRADES = 1  # must average >= 1 trade/day
QUICK = True   # fewer combos for fast result; set False for exhaustive run

OUT_DIR = ROOT / "data"
OUT_DIR.mkdir(exist_ok=True)

# Pre-generate data once (60d so tpd >= 1 is achievable)
BACKTEST_DAYS = DAYS
print("Generating data once...")
DF_1M, DF_15M = generate_backtest_data(trading_days=BACKTEST_DAYS, seed=SEED)
print(f"  1m bars: {len(DF_1M)}, 15m bars: {len(DF_15M)}")

# ── Parameter search space ─────────────────────────────────────────────────
SPACE = {
    "min_rr": [1.5, 1.7, 1.8, 2.0, 2.2, 2.5],
    "level_tolerance_pts": [4.0, 6.0, 8.0, 10.0, 14.0],
    "max_trades_per_day": [1, 2, 3, 4, 5],
    "skip_first_minutes": [0, 5, 10, 15],
    "min_body_pts": [0.0, 1.0, 2.0, 3.0],
    "max_risk_pts": [150.0, 200.0, 280.0, 350.0, 500.0],
    "require_trend_only": [True, False],
    "retest_only": [True, False],
    "fallback_after_min": [60, 90, 120, 150],
    "fallback_min_rr": [1.4, 1.5, 1.6, 1.7],
}


@dataclass
class Config:
    min_rr: float
    level_tolerance_pts: float
    max_trades_per_day: int
    skip_first_minutes: int
    min_body_pts: float
    max_risk_pts: float
    require_trend_only: bool
    retest_only: bool
    fallback_after_min: int
    fallback_min_rr: float


@dataclass
class Result:
    cfg: Config
    pnl: float
    ret_pct: float
    win_rate: float
    profit_factor: float
    max_dd_pct: float
    total_trades: int
    trades_per_day: float
    score: float


def score_result(r: Result) -> float:
    """Composite: high PnL, return, win rate, PF; low DD; >= 1 trade/day."""
    if r.total_trades == 0:
        return -9999.0
    tpd = r.trades_per_day
    if tpd < MIN_TRADES:
        return -9999.0
    pnl_score = r.ret_pct * 3.0
    wr_score = r.win_rate * 2.0
    pf_score = min(r.profit_factor, 10) * 15.0
    dd_penalty = r.max_dd_pct * 4.0
    tpd_bonus = min(tpd, 3) * 5.0
    return pnl_score + wr_score + pf_score - dd_penalty + tpd_bonus


def _save_best(b: Result) -> None:
    try:
        (OUT_DIR / "best_config.json").write_text(json.dumps({
            "score": round(b.score, 2),
            "pnl": round(b.pnl, 2),
            "total_return_pct": round(b.ret_pct, 2),
            "win_rate_pct": round(b.win_rate, 1),
            "profit_factor": round(b.profit_factor, 2),
            "max_drawdown_pct": round(b.max_dd_pct, 2),
            "total_trades": b.total_trades,
            "trades_per_day": round(b.trades_per_day, 2),
            "params": asdict(b.cfg),
        }, indent=2), encoding="utf-8")
    except Exception:
        pass


def run_config(cfg: Config) -> Result | None:
    try:
        engine = BacktestEngine(
            initial_balance=BALANCE,
            risk_per_trade_usd=RISK,
            min_rr=cfg.min_rr,
            level_tolerance_pts=cfg.level_tolerance_pts,
            max_trades_per_day=cfg.max_trades_per_day,
            skip_first_minutes=cfg.skip_first_minutes,
            min_body_pts=cfg.min_body_pts,
            max_risk_pts=cfg.max_risk_pts,
            require_trend_only=cfg.require_trend_only,
            retest_only=cfg.retest_only,
            fallback_after_minutes=cfg.fallback_after_min,
            fallback_min_rr=cfg.fallback_min_rr,
        )
        bt = engine.run(DF_1M, DF_15M)
        tpd = bt.total_trades / BACKTEST_DAYS
        res = Result(
            cfg=cfg,
            pnl=bt.final_balance - bt.initial_balance,
            ret_pct=bt.total_return_pct,
            win_rate=bt.win_rate_pct,
            profit_factor=bt.profit_factor,
            max_dd_pct=bt.max_drawdown_pct,
            total_trades=bt.total_trades,
            trades_per_day=tpd,
            score=0.0,
        )
        res.score = score_result(res)
        return res
    except Exception:
        return None


# ── Phase 1: Coarse grid ───────────────────────────────────────────────────
print("\n-- Phase 1: Coarse grid search ---------------------------------------")

if QUICK:
    coarse = {
        "min_rr": [1.5, 1.8, 2.0],
        "level_tolerance_pts": [6.0, 10.0],
        "max_trades_per_day": [2, 3],
        "skip_first_minutes": [0, 10],
        "min_body_pts": [0.0, 2.0],
        "max_risk_pts": [200.0, 350.0],
        "require_trend_only": [True],
        "retest_only": [True],
        "fallback_after_min": [90, 120],
        "fallback_min_rr": [1.5, 1.7],
    }
else:
    coarse = {
        "min_rr": [1.5, 2.0],
        "level_tolerance_pts": [6.0, 10.0],
        "max_trades_per_day": [2, 4],
        "skip_first_minutes": [0, 10],
        "min_body_pts": [0.0, 2.0],
        "max_risk_pts": [200.0, 350.0],
        "require_trend_only": [True, False],
        "retest_only": [True, False],
        "fallback_after_min": [90, 120],
        "fallback_min_rr": [1.5, 1.7],
    }

keys = list(coarse.keys())
combos = list(itertools.product(*coarse.values()))
total = len(combos)
print(f"  Testing {total} coarse combinations...")

all_results: list[Result] = []
best: Result | None = None

for i, vals in enumerate(combos):
    cfg = Config(**dict(zip(keys, vals)))
    res = run_config(cfg)
    if res:
        all_results.append(res)
        if best is None or res.score > best.score:
            best = res
            if best.score > -9999:
                _save_best(best)
    if (i + 1) % 100 == 0 or (i + 1) == total:
        if best:
            print(f"  [{i+1}/{total}]  Best -> score={best.score:.1f}  PnL=${best.pnl:+,.0f}  WR={best.win_rate:.1f}%  PF={best.profit_factor:.2f}  DD={best.max_dd_pct:.1f}%  T/D={best.trades_per_day:.2f}", flush=True)

if not best:
    print("  No valid result from coarse grid; running default config...")
    default_cfg = Config(
        min_rr=1.8,
        level_tolerance_pts=8.0,
        max_trades_per_day=3,
        skip_first_minutes=0,
        min_body_pts=0.0,
        max_risk_pts=350.0,
        require_trend_only=True,
        retest_only=True,
        fallback_after_min=90,
        fallback_min_rr=1.5,
    )
    best = run_config(default_cfg)
    if best:
        all_results.append(best)
        _save_best(best)
if not best:
    print("  ERROR: Could not get any valid backtest.")
    sys.exit(1)
print(f"\n  Coarse best: score={best.score:.2f}")

# ── Phase 2: Refined grid around best ──────────────────────────────────────
print("\n-- Phase 2: Refined search around best config ------------------------")


def neighborhood(val, space_vals, n=2):
    lst = sorted(set(space_vals), key=lambda x: (x if isinstance(x, (int, float)) else str(x)))
    try:
        idx = lst.index(val)
    except (ValueError, TypeError):
        if isinstance(val, bool):
            return list(space_vals)
        idx = min(range(len(lst)), key=lambda i: abs(lst[i] - val) if isinstance(lst[i], (int, float)) else 0)
    lo = max(0, idx - n)
    hi = min(len(lst), idx + n + 1)
    return lst[lo:hi]


n_fine = 1 if QUICK else 2
fine = {
    "min_rr": neighborhood(best.cfg.min_rr, SPACE["min_rr"], n_fine),
    "level_tolerance_pts": neighborhood(best.cfg.level_tolerance_pts, SPACE["level_tolerance_pts"], n_fine),
    "max_trades_per_day": neighborhood(best.cfg.max_trades_per_day, SPACE["max_trades_per_day"], n_fine),
    "skip_first_minutes": neighborhood(best.cfg.skip_first_minutes, SPACE["skip_first_minutes"], 1),
    "min_body_pts": neighborhood(best.cfg.min_body_pts, SPACE["min_body_pts"], 1),
    "max_risk_pts": neighborhood(best.cfg.max_risk_pts, SPACE["max_risk_pts"], n_fine),
    "require_trend_only": [True, False] if not QUICK else [best.cfg.require_trend_only],
    "retest_only": [True, False] if not QUICK else [best.cfg.retest_only],
    "fallback_after_min": neighborhood(best.cfg.fallback_after_min, SPACE["fallback_after_min"], n_fine),
    "fallback_min_rr": neighborhood(best.cfg.fallback_min_rr, SPACE["fallback_min_rr"], n_fine),
}

keys2 = list(fine.keys())
combos2 = list(itertools.product(*fine.values()))
MAX_FINE = 1500 if QUICK else 2500
if len(combos2) > MAX_FINE:
    random.seed(SEED)
    combos2 = list(combos2)
    random.shuffle(combos2)
    combos2 = combos2[:MAX_FINE]
    print(f"  Capped to {MAX_FINE} fine combinations (from full grid)...")
print(f"  Testing {len(combos2)} fine combinations...")

for i, vals in enumerate(combos2):
    cfg = Config(**dict(zip(keys2, vals)))
    res = run_config(cfg)
    if res:
        all_results.append(res)
        if res.score > best.score:
            best = res
            if best.score > -9999:
                _save_best(best)
    if (i + 1) % 100 == 0 or (i + 1) == len(combos2):
        if best:
            print(f"  [{i+1}/{len(combos2)}]  Best -> score={best.score:.1f}  PnL=${best.pnl:+,.0f}  WR={best.win_rate:.1f}%  PF={best.profit_factor:.2f}  DD={best.max_dd_pct:.1f}%  T/D={best.trades_per_day:.2f}", flush=True)

# ── Phase 3: Hill climbing from best ────────────────────────────────────────
print("\n-- Phase 3: Hill climbing from best config ---------------------------")


def hill_climb(start: Result, rounds=8) -> Result:
    current = start
    for rnd in range(rounds):
        improved = False
        for key in keys:
            for val in SPACE[key]:
                d = asdict(current.cfg)
                d[key] = val
                cfg = Config(**d)
                res = run_config(cfg)
                if res and res.score > current.score:
                    current = res
                    improved = True
                    if current.score > -9999:
                        _save_best(current)
        if not improved:
            break
        print(f"  Round {rnd+1}: score={current.score:.2f}  PnL=${current.pnl:+,.0f}  WR={current.win_rate:.1f}%  PF={current.profit_factor:.2f}  DD={current.max_dd_pct:.1f}%", flush=True)
    return current


best = hill_climb(best, rounds=5 if QUICK else 8)
all_results.append(best)

# ── Save results ───────────────────────────────────────────────────────────
all_results.sort(key=lambda r: r.score, reverse=True)
top20 = all_results[:20]

out_csv = OUT_DIR / "opt_results.csv"
with open(out_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow([
        "rank", "score", "pnl", "ret_pct", "win_rate", "profit_factor", "max_dd_pct",
        "total_trades", "trades_per_day",
        "min_rr", "level_tol", "max_trades_per_day", "skip_first", "min_body", "max_risk_pts",
        "require_trend", "retest_only", "fallback_min", "fallback_rr",
    ])
    for rank, r in enumerate(top20, 1):
        w.writerow([
            rank, round(r.score, 2), round(r.pnl, 2), round(r.ret_pct, 2), round(r.win_rate, 1),
            round(r.profit_factor, 2), round(r.max_dd_pct, 2), r.total_trades, round(r.trades_per_day, 2),
            r.cfg.min_rr, r.cfg.level_tolerance_pts, r.cfg.max_trades_per_day, r.cfg.skip_first_minutes,
            r.cfg.min_body_pts, r.cfg.max_risk_pts, r.cfg.require_trend_only, r.cfg.retest_only,
            r.cfg.fallback_after_min, r.cfg.fallback_min_rr,
        ])

b = best
(OUT_DIR / "best_config.json").write_text(json.dumps({
    "score": round(b.score, 2),
    "pnl": round(b.pnl, 2),
    "total_return_pct": round(b.ret_pct, 2),
    "win_rate_pct": round(b.win_rate, 1),
    "profit_factor": round(b.profit_factor, 2),
    "max_drawdown_pct": round(b.max_dd_pct, 2),
    "total_trades": b.total_trades,
    "trades_per_day": round(b.trades_per_day, 2),
    "params": asdict(b.cfg),
}, indent=2), encoding="utf-8")

print(f"\n{'='*60}")
print(f"  OPTIMIZATION COMPLETE  ({len(all_results)} configs tested)")
print(f"{'='*60}")
print(f"  Net PnL:         ${b.pnl:+,.2f}  ({b.ret_pct:+.2f}%)")
print(f"  Win Rate:        {b.win_rate:.1f}%")
print(f"  Profit Factor:   {b.profit_factor:.2f}")
print(f"  Max Drawdown:    {b.max_dd_pct:.2f}%")
print(f"  Total Trades:    {b.total_trades}  ({b.trades_per_day:.2f}/day)")
print(f"  Score:           {b.score:.2f}")
print(f"{'='*60}")
print(f"  Best params: {asdict(b.cfg)}")
print(f"\n  Saved: {out_csv}")
print(f"  Saved: {OUT_DIR / 'best_config.json'}")
