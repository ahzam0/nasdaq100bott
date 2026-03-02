# Strategy Trained for Live Market

**Trained:** 2026-03-01 12:24 EST  
**Data:** Yahoo NQ=F, 3 months, 7-11 EST. Train = first ~2 months, Validation = last 30 days.

## Best parameters (applied to config.py)

| Parameter | Value |
|-----------|--------|
| MAX_RISK_PER_TRADE_USD | 370 |
| MIN_RR_RATIO | 1.8 |
| LEVEL_TOLERANCE_PTS | 8.0 |
| MAX_RISK_PTS | 350.0 |
| SKIP_FIRST_MINUTES | 0 |
| RETEST_ONLY | True |
| MIN_BODY_PTS | 0.0 |

## Full 3-month backtest (best config)

| Metric | Result |
|--------|--------|
| Net P&L | $+21,876.25 (+43.75%) |
| Trades | 51 (W=33 L=18) |
| Win rate | 64.7% |
| Max drawdown | $1,762.50 (2.89%) |
| Profit factor | 7.23 |

## Live-market checklist

- [x] Parameters optimized on recent live data with train/validation split
- [x] **Auto-retrain**: enabled in app; runs weekly (Sunday 8 PM EST by default). Restart bot to apply new params after retrain.
- [ ] Run backtest before each session: `python run_backtest.py --live --months 1`
- [ ] USE_LIVE_FEED = True in config (or env MNQ_USE_LIVE_FEED=true)
- [ ] Telegram credentials set for alerts
- [ ] Start bot during session: `python main.py`
- [ ] Optional: run Price API for lower latency: `python -m api.price_server`
