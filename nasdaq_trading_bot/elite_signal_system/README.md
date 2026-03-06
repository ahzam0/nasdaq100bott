# Elite Trading Signal System

## Mission

Deliver a rule-based trading system that meets **all 5** performance targets simultaneously:

| Metric | Minimum |
|--------|---------|
| Signals per day | ≥ 1 (every trading day) |
| Win rate | ≥ 70% |
| Monthly return | ≥ 40% |
| Profit factor | ≥ 2.0 |
| Maximum drawdown | < 15% |

## Hit-and-trial protocol

1. **Design** a strategy (trend, breakout, mean reversion, MTF, hybrid).
2. **Backtest** on ≥ 90 days (60+ trades), with spread and slippage.
3. **Measure** all 5 metrics.
4. **If all pass** → deliver the strategy.
5. **If any fail** → diagnose, then adjust or change strategy.
6. **Repeat** from step 2 until all 5 are met.

## How to run

From project root:

```bash
python -m elite_signal_system.run_elite
```

Or:

```bash
py -m elite_signal_system.run_elite
```

The optimizer runs multiple rounds over assets (QQQ, SPY, AAPL) and strategies (trend_following, breakout, mean_reversion, hybrid), then prints the best result and diagnostic suggestions.

## Structure

- **config.py** — Targets, risk rules (max 2% per trade, min 1:2 RR), backtest settings.
- **signal_format.py** — `Signal` dataclass and daily output format (entry, SL, TP, confluences, confidence, invalidation).
- **metrics.py** — Compute signals/day, win rate, monthly return, profit factor, max DD; `all_targets_met()`.
- **backtest_engine.py** — Run backtest with SL/TP, 2% risk, spread, slippage; returns equity curve and trades.
- **strategies/** — Trend, breakout, mean reversion, hybrid (each returns list of `(bar_index, direction, entry, sl, tp)`).
- **optimizer_loop.py** — Hit-and-trial loop; diagnose and report.
- **daily_signals.py** — Format daily signal report.
- **weekly_monthly_tracker.py** — Weekly summary and monthly audit format.

## Absolute rules (never break)

- Never generate a signal without a stop loss.
- Never risk more than 2% per trade.
- Never take a trade with less than 1:2 risk-to-reward.
- Never declare success until all 5 metrics are met over ≥ 30 days (backtest or live).
- After 3 optimization rounds without meeting targets, document best result and suggested next strategy.
