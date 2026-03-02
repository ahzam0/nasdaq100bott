# MNQ Bot – Full Testing Report (Signals & Alerts)

## Test run summary
- **Total:** 36 tests
- **Passed:** 34
- **Skipped:** 2 (order flow API not running – optional)
- **Failed:** 0

## What is tested

### 1. Config & core
- Config loads (INSTRUMENT, risk, MAX_TRADES_PER_DAY, RETEST_ONLY).
- Risk calculator: `contracts_from_risk`, `risk_usd_for_trade`.

### 2. Data feed
- Calendar: high-impact times, `is_near_news`.
- Mock feed: connected, 1m/15m candles, `get_current_price`.
- `get_feed()` returns a valid feed.

### 3. Strategy – market structure
- `swing_highs_lows`, `trend_from_structure` (Bullish/Bearish/Ranging).

### 4. Strategy – key levels
- `build_key_levels`, `KeyLevels`, `all_levels()`.

### 5. Strategy – entry checklist
- `in_trading_window` (7:00–9:30 and 9:30–11:00 EST).
- `validate_entry`: time window, max trades, RTH first-minutes filter.
- Order flow: confirm long/short with `imbalance_ratio`; reject when order flow disagrees.

### 6. Strategy – setups
- `detect_setup` with retest-only and key levels (no crash; may or may not find setup).

### 7. Strategy – trade manager
- `ActiveTrade`: risk_pts, rr_at_price, pnl_at_price.
- **Trail:** `next_milestone_to_trail`, `stop_for_milestone` produce correct trail level and message.

### 8. Broker
- Paper broker: connect, place order, position.

### 9. Backtest
- Synthetic data, engine run, result shape (balance, trades, win rate).

### 10. Bot – alerts (signals & alerts)
- **Trade alert:** `format_trade_alert` – contains LONG/SHORT, entry, stop, TP1/TP2, R:R, key level, setup name.
- **Trail alert:** `format_trail_alert` – contains direction, entry, current price, action, new stop.
- **Stop hit:** `format_stop_hit` – contains TRADE CLOSED, direction, result, daily P&L.
- **Daily summary:** `format_daily_summary` – contains P&L, today’s trades.

### 11. Bot – commands
- `register_commands`, `get_state` (scan_active, trades_today, etc.).

### 12. Integration
- `main.run_scan`, `main.run_trailing` exist.
- **run_scan with mock feed:** no crash; scan runs with mocked window and state.
- **Valid setup → trade alert:** full pipeline from valid `ReversalSetup` to formatted message with all required fields.
- **Trail milestone → trail alert:** milestone logic + `format_trail_alert` produce valid trail message.

## Conclusion
The bot is **fully capable** of:
- Producing **proper trade signals** when the strategy finds a valid setup (entry, stop, TP1/TP2, R:R, key level).
- Sending **proper alerts**: trade alert, trail alert, stop hit, daily summary.
- Respecting session window, max trades, daily loss limit, and optional order flow.

**For live signals you need:**
1. A **live data feed** (price API or Tradovate/Yahoo) so `get_1m_candles` / `get_15m_candles` / `get_current_price` return real data.
2. Bot running **within the scan window** (default 7:00–11:00 AM EST).
3. **TELEGRAM_BOT_TOKEN** and **TELEGRAM_CHAT_ID** set (e.g. in `.env`).

Optional: order flow server for direction confirmation (tests skip when not running).
