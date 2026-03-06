# NASDAQ (NAS100/NDX) Trading Strategies

Top proven approaches used by professional traders. No single "best" — choose by style, risk, and timeframe.

## 1. Trend Following (Swing & Position)

- **200 EMA** on daily for macro trend: long above, short below.
- Confirm with **MACD** crossovers and **RSI > 50** (long) / **RSI < 50** (short).
- Hold **days to weeks**.

## 2. Smart Money Concepts (SMC) — Day Trading

- Identify **liquidity pools** (equal highs/lows where stops cluster).
- Wait for **sweep** of liquidity, then **reversal**.
- Enter on **displacement candle** (strong momentum shift).
- Best during **NY Kill Zone: 9:30–11:00 AM EST**.

## 3. Breakout Trading — Momentum

- Mark **key weekly/daily highs and lows**.
- Wait for **clean candle close** above resistance or below support.
- Enter on **retest** of the broken level.
- Target next significant structure level.

## 4. Multi-Timeframe Intraday — All-Around

- **HTF (Daily/4H):** Define bias — bullish or bearish.
- **MTF (1H):** Key structure to trade from.
- **LTF (15/5 min):** Refine entry trigger.
- Stops at previous highs (shorts) or lows (longs); targets at daily/weekly structure.
- **Risk 1%**, aim for **3:1 reward-to-risk** minimum.

## 5. Momentum/Risk-Adjusted — Investors

- Risk-adjusted momentum: top-performing NASDAQ names.
- Variable allocation to **treasuries or gold** to smooth equity curve and crash protection in bear markets.

---

## Risk Management (Non-Negotiable)

- **Never risk more than 1–2% per trade.**
- **Always use a stop-loss** — no exceptions.
- **Diversify:** balance NQ with uncorrelated markets (gold, crude, commodities).
- **Avoid trading** during major news (CPI, FOMC) unless you have a news-specific strategy.

---

## Best Times to Trade NASDAQ

- **NY Kill Zone:** 9:30–11:00 AM EST (best for SMC / day trading).
- **Regular session:** 9:30 AM – 4:00 PM EST.
- **Power hour:** 3:00–4:00 PM EST (higher volatility).
- Avoid: first 15–30 min (chaotic open), lunch 12:00–1:30 PM (lower volume).

---

Code: `strategies/` — `TrendFollowingNasdaqStrategy`, `SmartMoneyNasdaqStrategy`, `BreakoutNasdaqStrategy`, `MultiTimeframeNasdaqStrategy`, `MomentumRiskAdjustedNasdaqStrategy`. Risk/session helpers: `strategies/risk_rules.py`, `strategies/best_times.py`.
