# MNQ Bot – Full A-to-Z QA & Testing Report

**Date:** 2026-03-01  
**Scope:** Unit tests, integration, backtests (synthetic + live 7d + live 3mo + order-flow proxy), entry points, config, order flow API, lint. Quality assurance sign-off.

---

## 1. Unit & Integration Tests

**Command:** `python run_tests.py`

| Result | Count |
|--------|--------|
| **Passed** | **18** |
| **Failed** | 0 |
| **Time** | ~14–22s |

### Coverage

| Area | Tests |
|------|--------|
| **Config** | Load, INSTRUMENT=MNQ, MAX_RISK_PER_TRADE_USD=380, MAX_TRADES_PER_DAY, RETEST_ONLY |
| **Utils** | contracts_from_risk, risk_usd_for_trade |
| **Data** | MockDataFeed, get_1m_candles, get_current_price, get_feed |
| **Market structure** | swing_highs_lows, trend_from_structure |
| **Key levels** | build_key_levels, KeyLevels, all_levels() |
| **Entry checklist** | in_trading_window, validate_entry (max trades), validate_entry with orderflow_summary, check_orderflow reject |
| **Trade manager** | ActiveTrade risk_pts, rr_at_price, pnl_at_price |
| **Setups** | detect_setup (retest_only) |
| **Broker** | PaperBroker, get_broker, place_market_order, position |
| **Backtest** | BacktestEngine on 3-day synthetic data, result fields |
| **Bot** | format_trade_alert, format_trail_alert, format_stop_hit, format_daily_summary; register_commands, get_state |
| **Integration** | main.run_scan / run_trailing; run_backtest.print_report / main |
| **Order flow** | GET /orderflow/summary shape; main._fetch_orderflow_summary returns dict with age_seconds, imbalance_ratio |

---

## 2. Backtests

| Test | Command | Status | Result |
|------|---------|--------|--------|
| **Synthetic 3d** | `run_backtest.py --days 3 --balance 50000 --risk 380` | OK | 0 trades (seed=42), balance $50,000 |
| **Live 7d** | `run_backtest.py --live --balance 50000` | OK | 4 trades, +$429.50, 1.74% DD |
| **Live 3mo** | `run_backtest.py --live --months 3 --balance 50000` | OK | 51 trades, +$21,984.25, 64.7% WR, 2.88% DD, PF 7.26 |
| **Live 3mo + OF proxy** | `run_backtest.py --live --months 3 --balance 50000 --use-orderflow-proxy` | OK | 38 trades, +$16,784.25, 60.5% WR, 3.18% DD |

---

## 3. Entry Points & Config

| Check | Status |
|-------|--------|
| config.INSTRUMENT, MAX_RISK_PER_TRADE_USD=380, LEVEL_TOLERANCE_PTS=8, MIN_RR_RATIO=1.8, MAX_RISK_PTS=350 | OK |
| main.run_scan, main.run_trailing, main.main, main._fetch_orderflow_summary | OK |
| run_backtest.print_report, run_backtest.main | OK |
| train_for_live.run_auto_retrain | OK |
| strategy.validate_entry, check_orderflow, build_key_levels, detect_setup | OK |
| data.orderflow.get_orderflow_store, OrderFlowSummary | OK |
| bot.register_commands, get_state, format_trade_alert, send_telegram | OK |

---

## 4. Lint

- **Files:** main.py, config.py, run_backtest.py, backtest/engine.py, strategy/entry_checklist.py  
- **Result:** No linter errors.

---

## 5. Order Flow

| Item | Status |
|------|--------|
| Order flow API (GET /orderflow/summary, POST /orderflow/push) | Implemented; tests require server on 5002 |
| main fetches summary when USE_ORDERFLOW and ORDERFLOW_API_URL set | OK |
| Checklist uses age_seconds, imbalance_ratio; rejects when ORDERFLOW_REQUIRE_CONFIRM and summary disagrees | OK (test_validate_entry_with_orderflow_summary, test_check_orderflow) |
| Backtest --use-orderflow-proxy | OK; candle-based proxy applied |

---

## 6. Quality Assurance Checklist

- [x] All unit/integration tests pass (18/18)
- [x] Synthetic backtest runs without error
- [x] Live 7-day and 3-month backtests run and produce expected report
- [x] Backtest with --use-orderflow-proxy runs and reduces trade count
- [x] Config and all entry points load and resolve
- [x] No linter errors on core files
- [x] Order flow fetch and checklist path covered by tests
- [x] TRAIN_LIVE_RESULT / BACKTEST_3M_RESULT reflect current config (risk $380, level_tol 8)

---

## 7. How to Re-run Full QA

```powershell
cd d:\younas\mnq_bot

# 1. Unit + integration + order flow tests (order flow server must be running for 2 tests)
python -m api.orderflow_server   # in another terminal, then:
python run_tests.py

# 2. Backtests
python run_backtest.py --days 3 --balance 50000
python run_backtest.py --live --balance 50000
python run_backtest.py --live --months 3 --balance 50000
python run_backtest.py --live --months 3 --balance 50000 --use-orderflow-proxy

# 3. Entry point verification
python -c "import config, main, run_backtest, train_for_live; from strategy import validate_entry; from data.orderflow import get_orderflow_store; from bot import register_commands; print('OK')"
```

---

## Summary

| Category | Status |
|----------|--------|
| Unit/Integration tests | 18/18 pass |
| Synthetic backtest | Pass |
| Live 7d backtest | Pass |
| Live 3mo backtest | Pass |
| Live 3mo + order flow proxy | Pass |
| Entry points & config | OK |
| Lint | No errors |
| Order flow integration | OK |

**QA sign-off:** Full app testing and quality assurance completed. The application is ready for use (paper/live per config). For production, run `python main.py` during session and optionally start the Order Flow API and Price API as documented.
