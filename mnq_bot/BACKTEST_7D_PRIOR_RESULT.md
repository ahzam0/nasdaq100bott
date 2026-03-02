# 7-day live backtest – prior result (reproducible via saved data when available)

**Data:** NQ=F, last 7 days, 7–11 EST — **1,446 1m bars**, **102 15m bars**

## Results

| Metric | Value |
|--------|--------|
| Initial balance | $50,000 |
| Final balance | $51,588 |
| Net P&L | **+$1,588** |
| Total return | **+3.18%** |
| Total trades | **4** |
| Win rate | **75%** (3W / 1L) |
| Profit factor | **5.99** |
| Max drawdown | $318 (0.63%) |
| Avg R per trade | 0.50R |

## Last 10 trades (all 4)

- 2026-02-23 LONG +$652 (stop exit)
- 2026-02-24 SHORT -$318 (stop)
- 2026-02-27 SHORT +$626 (stop exit)
- 2026-02-27 SHORT +$628 (stop exit)

---

To reproduce similar results in the future:

1. When a good live run happens, save the data:  
   `python run_backtest.py --live --balance 50000 --risk 330 --save-data backtest_7d`
2. Replay anytime:  
   `python run_backtest.py --load-data backtest_7d --balance 50000 --risk 330`
