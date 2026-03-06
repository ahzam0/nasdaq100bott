# NASDAQ 100 (NAS100) Elite Signal System

## Asset

- **Instrument:** NAS100 / US100 (CFD)
- **Leverage:** 1:20 minimum, 1:50 recommended
- **Point value:** ~$1 per point per 1 lot
- **Data proxy:** ^NDX (NASDAQ-100 index) for backtest

## Non-negotiable targets (all 5 simultaneously)

| # | Metric           | Target    |
|---|------------------|-----------|
| 1 | Win rate         | ≥ 70%     |
| 2 | Monthly return   | ≥ 40%     |
| 3 | Max drawdown     | ≤ 15%     |
| 4 | Profit factor    | ≥ 2.0     |
| 5 | Signals per day  | ≥ 1       |

## Strategies

1. **ORB** — Opening range breakout (prev day high/low); D1 trend + volume.
2. **Order Block** — Last candle before 3+ bar impulse; pullback into zone.
3. **Key Level** — PDH/PDL rejection; RSI; 1:2.5–1:4 RR.
4. **Hybrid** — ORB + OB + Key Level; fallback 1 signal/day.

## Confluence (≥ 5/7 to enter)

- D1 trend vs 200 EMA  
- H4 structure  
- Price at key zone  
- M15 trigger  
- RSI not opposing  
- Volume confirms  
- RR ≥ 1:2  

Score 7 → 2% risk, 6 → 1.5%, 5 → 1%.

## Circuit breakers

- Daily loss ≥ 3% → stop for the day  
- Weekly loss ≥ 8% → stop for the week  
- Monthly loss ≥ 15% → stop for the month  
- 5 consecutive losses in a week → stop for the week  

## How to run

From project root:

```bash
python -m nas100_elite.run_nas100
```

## Structure

- **config.py** — Targets, sessions, SL/TP points, confluence, circuit breakers  
- **confluence.py** — 7-point score and risk %  
- **sizing.py** — Position size in lots from risk % and SL points  
- **strategies/** — ORB, OrderBlock, KeyLevel, Hybrid  
- **backtest_nas100.py** — Point-based P&L, circuit breakers  
- **metrics_nas100.py** — All 5 metrics + report  
- **signal_format.py** — Daily signal output format  
- **weekly_report.py** — Weekly tracker format  
- **optimizer_nas100.py** — Rounds 1–4 + risk optimization  

## Absolute rules (NASDAQ-specific)

1. No NAS100 in Asian session (00:00–07:00 EST).  
2. No entry 30 min before/after FOMC, NFP, CPI.  
3. SL never wider than 80 points.  
4. RR never below 1:2.  
5. Never move SL further away.  
6. No adding to a losing trade.  
7. Never break daily/weekly/monthly loss limits.  
8. Always check economic calendar.  
9. Enter on M15 candle close only.  
10. Log every trade.  
