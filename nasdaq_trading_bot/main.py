"""
NASDAQ Quantum Optimizer — entry point.
Modes: backtest | optimize | live | dashboard.
Runs iterative quantum-enhanced backtest until convergence or all 10 targets met.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Project root
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.engine import BacktestEngine
from backtest.metrics import Metrics, compute_metrics, count_targets_met, all_targets_met
from backtest.validation import validate_all
from data.pipeline import get_pipeline
from quantum.optimizer import QuantumOptimizer, params_to_strategy_kwargs
from strategies import TrendFollowingNasdaqStrategy
from utils.config import TARGETS, BACKTEST, OPTIMIZATION
from utils.leaderboard import Leaderboard
from utils.logger import setup_logging, log_iteration
from utils.scorer import composite, count_targets_met_from_metrics, all_targets_met_from_metrics

logger = logging.getLogger(__name__)

# Default assets (QQQ + mega caps + top universe)
ASSETS = [
    "QQQ", "TQQQ", "AAPL", "MSFT", "NVDA", "META", "GOOGL", "AMZN", "TSLA", "AMD",
    "SMCI", "PLTR", "CRWD", "MSTR", "AVGO", "ARM", "SNOW", "NET", "DDOG", "MDB",
]

TRAIN_START = BACKTEST.get("train_start", "2018-01-01")
TRAIN_END = BACKTEST.get("train_end", "2022-12-31")
OOS_START = BACKTEST.get("oos_start", "2023-01-01")
OOS_END = BACKTEST.get("oos_end", "2024-12-31")

MAX_ITER = int(OPTIMIZATION.get("max_iterations", 100_000))
CONVERGENCE_LOOKBACK = int(OPTIMIZATION.get("convergence_lookback", 500))
SHARPE_THRESH = float(OPTIMIZATION.get("sharpe_improvement_threshold", 0.001))
CAGR_THRESH_PCT = float(OPTIMIZATION.get("cagr_improvement_threshold_pct", 0.1))
DD_THRESH_PCT = float(OPTIMIZATION.get("dd_improvement_threshold_pct", 0.01))
NOISE_AFTER = int(OPTIMIZATION.get("quantum_noise_after_stagnant", 100))
DEPTH_AFTER = int(OPTIMIZATION.get("circuit_depth_increase_after", 50))
LEADERBOARD_SIZE = int(OPTIMIZATION.get("leaderboard_size", 100))
LOG_EVERY = int(OPTIMIZATION.get("log_every_n_iter", 100))


def _targets_dict() -> dict:
    """Config targets as dict for scorer/metrics."""
    t = TARGETS or {}
    return {
        "sharpe_ratio": t.get("sharpe_ratio", 5.0),
        "max_drawdown_pct": t.get("max_drawdown_pct", 5.0),
        "win_rate_pct": t.get("win_rate_pct", 70.0),
        "cagr_pct": t.get("cagr_pct", 150.0),
        "profit_factor": t.get("profit_factor", 3.0),
        "sortino_ratio": t.get("sortino_ratio", 6.0),
        "calmar_ratio": t.get("calmar_ratio", 4.0),
        "annual_volatility_pct": t.get("annual_volatility_pct", 12.0),
        "expectancy_per_r": t.get("expectancy_per_r", 2.5),
        "max_consecutive_losses": t.get("max_consecutive_losses", 3),
    }


def _converged(history: list, lookback: int) -> bool:
    """True if no improvement in Sharpe/CAGR/MaxDD over last lookback iterations."""
    if len(history) < lookback:
        return False
    recent = history[-lookback:]
    sharpe = [h.get("sharpe") for h in recent if h.get("sharpe") is not None]
    cagr = [h.get("cagr") for h in recent if h.get("cagr") is not None]
    dd = [h.get("max_dd") for h in recent if h.get("max_dd") is not None]
    if not sharpe or not cagr or not dd:
        return False
    improve_sharpe = max(sharpe) - min(sharpe) > SHARPE_THRESH
    improve_cagr = max(cagr) - min(cagr) > CAGR_THRESH_PCT
    improve_dd = max(dd) - min(dd) > DD_THRESH_PCT
    if improve_sharpe or improve_cagr or improve_dd:
        return False
    return True


def _run_backtest(
    engine: BacktestEngine,
    prices: pd.Series,
    signals: pd.Series,
    benchmark_returns: pd.Series | None,
) -> tuple[pd.Series, pd.DataFrame, Metrics | None]:
    res = engine.run(prices, signals, benchmark_returns=benchmark_returns)
    return res.equity_curve, res.trades, res.metrics


def _build_signals(df: pd.DataFrame, params: np.ndarray, strategy_name: str, asset: str = "QQQ") -> pd.Series:
    kwargs = params_to_strategy_kwargs(params)
    ema_period = int(kwargs.get("ema_period", 200))
    strat = TrendFollowingNasdaqStrategy(ema_period=ema_period)
    return strat.generate_signals(df, df.attrs.get("symbol", asset))


def _passes_gates(metrics: Metrics | None, equity: pd.Series, returns: pd.Series) -> bool:
    """OOS gate and stress tests (simplified: require valid metrics and no blow-up)."""
    if metrics is None:
        return False
    if metrics.sharpe_ratio is not None and metrics.sharpe_ratio < -2.0:
        return False
    if metrics.max_drawdown_pct is not None and metrics.max_drawdown_pct > 80.0:
        return False
    return True


def run_optimize(dry_run: bool = False, asset: str = "QQQ") -> None:
    setup_logging("INFO")
    np.random.seed(42)
    targets = _targets_dict()
    engine = BacktestEngine(initial_balance=50_000.0)
    validator = validate_all
    leaderboard = Leaderboard(max_size=LEADERBOARD_SIZE)
    opt = QuantumOptimizer(param_dim=20, seed=42)

    # Load train data (primary asset)
    df = get_pipeline(asset, TRAIN_START, TRAIN_END, interval="1d", with_qqq=True)
    if df is None or df.empty or len(df) < 100:
        logger.warning("Insufficient train data for %s; using synthetic for demo.", asset)
        dates = pd.date_range(TRAIN_START, TRAIN_END, freq="B")
        np.random.seed(42)
        close = 100 + np.cumsum(np.random.randn(len(dates)) * 0.8)
        df = pd.DataFrame({
            "open": np.roll(close, 1),
            "high": close + np.abs(np.random.randn(len(dates))),
            "low": close - np.abs(np.random.randn(len(dates))),
            "close": close,
            "volume": np.full(len(dates), 1_000_000),
        }, index=dates)
        df["open"].iloc[0] = 100
    if df.empty or "close" not in df.columns:
        logger.error("No price data. Aborting.")
        return
    prices = df["close"]
    benchmark_returns = prices.pct_change().dropna()

    best_params: np.ndarray | None = None
    best_score = -np.inf
    best_metrics: Metrics | None = None
    run_number = 0
    strategy_name = "trend_following"

    while True:
        run_number += 1
        iterations = 0
        no_improve = 0
        metrics_history: list = []

        params = opt.initialize_random() if run_number == 1 else opt.mutate(best_params or opt.initialize_random(), noise=0.1)

        while iterations < (1000 if dry_run else MAX_ITER):
            candidate = opt.suggest(params)
            signals = _build_signals(df.copy(), candidate, strategy_name, asset)
            if signals is None or signals.empty:
                opt.penalize(candidate)
                iterations += 1
                continue
            equity, trades, metrics = _run_backtest(engine, prices, signals, benchmark_returns)
            if not _passes_gates(metrics, equity, equity.pct_change().dropna()):
                opt.penalize(candidate)
                iterations += 1
                continue
            score = composite(metrics, targets)
            opt.update_hamiltonian(metrics, score)
            metrics_history.append({
                "sharpe": metrics.sharpe_ratio,
                "cagr": metrics.cagr_pct,
                "max_dd": metrics.max_drawdown_pct,
            })

            if score > best_score * 1.001:
                best_params = candidate.copy()
                best_score = score
                best_metrics = metrics
                opt.set_best(candidate)
                no_improve = 0
                log_iteration(run_number, iterations, metrics, score, count_targets_met_from_metrics(metrics, targets))
            else:
                no_improve += 1
            params = candidate
            leaderboard.update(candidate, metrics, score, strategy_name)

            if no_improve > NOISE_AFTER:
                opt.inject_quantum_noise()
                no_improve = 0
            if no_improve > DEPTH_AFTER:
                opt.increase_circuit_depth()
                no_improve = 0

            if iterations % LOG_EVERY == 0 and metrics:
                targets_hit = count_targets_met_from_metrics(metrics, targets)
                print(
                    f"Run {run_number} | Iter {iterations:,} | "
                    f"Sharpe {metrics.sharpe_ratio:.2f} | CAGR {metrics.cagr_pct:.0f}% | "
                    f"MaxDD {metrics.max_drawdown_pct:.1f}% | Score {score:.4f} | "
                    f"Targets {targets_hit}/10"
                )
            iterations += 1

            if _converged(metrics_history, CONVERGENCE_LOOKBACK):
                break

        if all_targets_met_from_metrics(best_metrics, targets):
            print("ALL 10 NASDAQ TARGETS ACHIEVED — Global Maximum Found")
            break
        if dry_run or run_number >= 3:
            break
        print(f"Run {run_number} complete. Re-running with quantum noise...")

    # Final results block
    m = best_metrics
    t = targets
    print()
    print("=" * 50)
    print("  NASDAQ QUANTUM OPTIMIZER — FINAL RESULTS")
    print("=" * 50)
    if m:
        def tick(v, thr, higher_better):
            if higher_better:
                return "✅" if (v is not None and v >= thr) else "❌"
            return "✅" if (v is not None and v <= thr) else "❌"
        print(f"  Sharpe Ratio:          {m.sharpe_ratio:.2f}  [target >{t['sharpe_ratio']}]   {tick(m.sharpe_ratio, t['sharpe_ratio'], True)}")
        print(f"  Max Drawdown:          {m.max_drawdown_pct:.1f}% [target <{t['max_drawdown_pct']}%]    {tick(m.max_drawdown_pct, t['max_drawdown_pct'], False)}")
        print(f"  Win Rate:              {m.win_rate_pct:.1f}% [target >{t['win_rate_pct']}%]   {tick(m.win_rate_pct, t['win_rate_pct'], True)}")
        print(f"  CAGR:                  {m.cagr_pct:.0f}%  [target >{t['cagr_pct']}%]  {tick(m.cagr_pct, t['cagr_pct'], True)}")
        print(f"  Profit Factor:         {m.profit_factor:.2f}  [target >{t['profit_factor']}]   {tick(m.profit_factor, t['profit_factor'], True)}")
        print(f"  Sortino Ratio:         {m.sortino_ratio:.2f}  [target >{t['sortino_ratio']}]   {tick(m.sortino_ratio, t['sortino_ratio'], True)}")
        print(f"  Calmar Ratio:          {m.calmar_ratio:.2f}  [target >{t['calmar_ratio']}]   {tick(m.calmar_ratio, t['calmar_ratio'], True)}")
        print(f"  Annual Volatility:     {m.annual_volatility_pct:.1f}% [target <{t['annual_volatility_pct']}%]   {tick(m.annual_volatility_pct, t['annual_volatility_pct'], False)}")
        print(f"  Expectancy:            ${m.expectancy_per_r:.2f} [target >${t['expectancy_per_r']}] {tick(m.expectancy_per_r, t['expectancy_per_r'], True)}")
        print(f"  Max Consec Losses:     {m.max_consecutive_losses}     [target <{t['max_consecutive_losses']}]      {tick(m.max_consecutive_losses, t['max_consecutive_losses'], False)}")
    print("-" * 50)
    print(f"  TARGETS HIT: {count_targets_met_from_metrics(m, targets)}/10")
    print(f"  TOP STRATEGY: {strategy_name}")
    if best_params is not None:
        best_json = json.dumps(params_to_strategy_kwargs(best_params))
        print(f"  BEST PARAMS:  {best_json}")
    print("=" * 50)
    leaderboard.save()


def main() -> int:
    parser = argparse.ArgumentParser(description="NASDAQ Quantum Trading Bot")
    parser.add_argument("--mode", choices=["backtest", "optimize", "live", "dashboard"], default="optimize")
    parser.add_argument("--dry-run", action="store_true", help="Limit iterations for quick test")
    parser.add_argument("--asset", default="QQQ", help="Primary asset for backtest")
    args = parser.parse_args()
    if args.mode == "optimize":
        run_optimize(dry_run=args.dry_run, asset=args.asset)
    elif args.mode == "backtest":
        run_optimize(dry_run=True, asset=args.asset)
    else:
        print("Live and dashboard modes: use live/broker.py and dashboard/app.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
