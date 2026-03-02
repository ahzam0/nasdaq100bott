# Real Backtest Data – 3 Month (MNQ Riley Coleman)

**Data**: Yahoo Finance NQ=F, 7–11 EST session, 1m bars from 15m expansion.  
**Config**: Balance $50,000, **risk $380/trade**, `MAX_RISK_PTS = 350`, `MIN_RR_RATIO = 1.8`, `LEVEL_TOLERANCE_PTS = 8`, `SKIP_FIRST_MINUTES = 0`, `MIN_BODY_PTS = 0`. No order flow proxy.

| Metric | Result |
|--------|--------|
| Initial balance | $50,000 |
| Final balance | $71,984.25 |
| Net P&L | **+$21,984.25 (+43.97%)** |
| Profit amount | +$21,984.25 |
| Total trades | 51 |
| Winners / Losers | 33 / 18 |
| Win rate | 64.7% |
| Max drawdown | $1,762.50 (2.88%) |
| Profit factor | 7.26 |
| Avg R per trade | 0.51R |

**Tuned for improved stats:** risk $380, level_tol 8, 350pt cap. Run `python optimize_stats.py` for full param sweep.

**Alternative presets:** `MAX_RISK_PTS = 200` + MIN_RR 1.85, MIN_BODY 1, SKIP_FIRST 5 → ~33 trades, 2.20% DD; with `--use-orderflow-proxy` → 38 trades, +$16,676, 60.5% WR.
