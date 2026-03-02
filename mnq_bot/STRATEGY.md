# MNQ Riley Coleman Strategy

This document summarizes the **Riley Coleman–style price-action reversal strategy** used in this bot so it can be remembered and reused.

## What It Is
- **Instrument**: Micro E-mini NASDAQ-100 (MNQ).
- **Style**: Price-action **reversals at key levels** (swing highs/lows, round numbers), traded in the **7:00–11:00 EST** session.
- **Timeframes**: 1m for entry bars; 15m for trend and structure.

## Setup Types
- **Retest Reversal only** (no Failed Breakout) – better win rate and drawdown in backtests.
- Reversal patterns: bullish/bearish engulfing, pin bars at key levels.
- 15m trend must be Bullish or Bearish (not Ranging).

## Key Settings (Tuned for Low Drawdown)
| Setting | Value | Purpose |
|--------|--------|--------|
| `MAX_RISK_PTS` | 100.0 | Cap stop distance (points). Limits loss per trade; keeps max drawdown ~1% in 3mo backtest. |
| `LEVEL_TOLERANCE_PTS` | 4.0 | How close price must be to a key level. |
| `MIN_RR_RATIO` | 2.0 | Minimum reward:risk (e.g. 2R). |
| `MAX_TRADES_PER_DAY` | 3 | Max entries per day. |
| `REQUIRE_TREND_ONLY` | True | Only trade when 15m trend is Bullish/Bearish. |
| `RETEST_ONLY` | True | Only Retest Reversal setups. |

## Real Backtest Data (3 Months, Yahoo NQ=F)

Official reference numbers for the current strategy:

| Metric | Result |
|--------|--------|
| Initial balance | $50,000 |
| Final balance | $55,225.25 |
| Net P&L | +$5,225.25 (+10.45%) |
| Total trades | 17 |
| Winners / Losers | 14 / 3 |
| Win rate | 82.4% |
| Max drawdown | $570 (1.02%) |
| Profit factor | 10.17 |
| Avg R per trade | 0.24R |

Full snapshot: `BACKTEST_3M_RESULT.md`. Without the 100pt stop cap, drawdown was ~16%.

## Running a Backtest
```bash
python run_backtest.py --live --months 3 --balance 50000 --risk 330
```
Uses config defaults (including `MAX_RISK_PTS = 100`). For no stop cap, set `MAX_RISK_PTS = None` in `config.py` or add a CLI override.

## Where It Lives in Code
- **Config**: `config.py`
- **Strategy**: `strategy/` (key_levels, market_structure, setups, entry_checklist, trade_manager)
- **Backtest**: `backtest/engine.py`, `run_backtest.py`
- **Live**: `main.py`, `data/feed.py`

Keep this strategy in mind when changing logic or defaults: **retest-only reversals at key levels, with capped stop distance for low drawdown.**
