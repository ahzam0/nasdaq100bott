# Strategy Trained for Live Market

**Trained:** 2026-03-05 06:10 EST
**Data:** Yahoo NQ=F, 3 months, 7-11 EST. Train = first ~2 months, Validation = last 30 days.

## Best parameters (applied to config.py)

| Parameter | Value |
|-----------|--------|
| MAX_RISK_PER_TRADE_USD | 380 |
| MIN_RR_RATIO | 1.6 |
| LEVEL_TOLERANCE_PTS | 6.0 |
| MAX_RISK_PTS | 200.0 |
| REQUIRE_TREND_ONLY | True |
| MAX_TRADES_PER_DAY | 1 |
| MIN_BODY_PTS | 2.0 |
| TP1_RR | 1.6 |
| TP2_RR | 2.5 |
| SKIP_FIRST_MINUTES | 0 |
| RETEST_ONLY | True |

## Full 3-month backtest (best config)

| Metric | Result |
|--------|--------|
| Net P&L | $+14,315.00 (+28.63%) |
| Trades | 20 (W=19 L=1) |
| Win rate | 95.0% |
| Max drawdown | $190.00 (0.32%) |
| Profit factor | 76.34 |

## Live-market checklist

- [x] Parameters optimized on recent live data with train/validation split
- [ ] Run backtest before each session: `python run_backtest.py --live --months 1`
- [ ] USE_LIVE_FEED = True in config (or env MNQ_USE_LIVE_FEED=true)
- [ ] Telegram credentials set for alerts
- [ ] Start bot during session: `python main.py`
- [ ] Optional: run Price API for lower latency: `python -m api.price_server`
