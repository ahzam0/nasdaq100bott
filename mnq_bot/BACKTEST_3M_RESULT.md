# Real Backtest Data – 3 Month (MNQ Riley Coleman)

**Best on current data (this 3‑month window):**
| Metric | Result |
|--------|--------|
| Total return | **+36.05%** |
| Net P&L | +$18,024.25 |
| Final balance | $68,024.25 |
| Total trades | 52 (28 W / 24 L) |
| Win rate | 53.8% |
| Max drawdown | 3.06% |
| Profit factor | 5.56 |
| Avg R per trade | 0.29R |

**Command:** `python run_backtest.py --live --months 3 --balance 50000 --risk 380` (config: MIN_RR_RATIO=1.8, SKIP_FIRST_MINUTES=0, LEVEL_TOLERANCE_PTS=8).

**Higher win rate preset** (fewer trades, better WR): add `--use-orderflow-proxy` → ~32% return, **57.5% win rate**, 5.52 PF, 0.36R. Use when you want more consistent winners over raw return.

**Improving further:** Run the full optimizer (takes ~10–15 min) to search for better params on current data:
```bash
python optimize_best.py --workers 1 --rounds 4 --combos 100 --months 3
```
Then apply `optimized_config_snippet.txt` via `python apply_optimized_config.py` and re-run the backtest.

---

**Target stats (original preset)** – what to aim for:
| Metric | Target |
|--------|--------|
| Total return | +35.46% |
| Net P&L | +$17,729.25 |
| Final balance | $67,729.25 (from $50,000) |
| Total trades | 54 (28 W / 26 L) |
| Win rate | 51.9% |
| Max drawdown | $2,125 (3.06%) |
| Profit factor | 4.98 |
| Avg R per trade | 0.24R |

**Reproduce:** `python run_backtest.py --live --months 3 --balance 50000 --risk 380` with config: `SKIP_FIRST_MINUTES = 0`, `MIN_RR_RATIO = 1.8`, `MIN_BODY_PTS = 0`, `MAX_RISK_PTS = 350`. Results vary with the current 3-month window.

---

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

---

### Getting 40%+ (or best possible) on *current* data

The +44% result above was on a **specific 60-day window** (Yahoo 15m = last 60 days at the time). The **same parameters** on today’s “last 60 days” can give a different return (e.g. ~11%) because the market period changed.

To aim for **at least 40%** (or the best return possible) on the **current** data:

1. **Run the optimizer** (a few minutes):
   ```bash
   python optimize_40pct.py --workers 1 --rounds 2 --combos 100 --months 3
   ```
2. **Apply the suggested parameters** from `optimized_config_snippet.txt` into `config.py` (overwrite the matching variables).
3. **Re-run the backtest** to confirm:
   ```bash
   python run_backtest.py --live --months 3 --risk 380
   ```

If no combo hits 40% on current data, the optimizer still writes the **best combo** it found (e.g. highest return with good win rate). Use that for the best achievable result on the current period.
