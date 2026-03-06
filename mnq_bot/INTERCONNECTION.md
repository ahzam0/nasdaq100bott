# MNQ Bot – Interconnection Overview

Quick reference for how main components are wired. Verified and fixed as needed.

## Entry points

| Entry | Purpose |
|-------|--------|
| **main.py** | Polling mode: PTB app, scan every 60s, daily summary, session-end job, trailing. |
| **run_bot_pa.py** | Webhook mode (PA/Railway): Flask app, POST /webhook, /cron/scan (and optional /cron/session-end). |
| **run_backtest.py** | Backtest (synthetic or --live Yahoo). |

- **Polling**: `main.main()` builds the app, registers commands, runs `scan_job` every 60s, `daily_summary_job` at **DAILY_SUMMARY_HOUR** (config), `session_end_feed_job` at **RTH_END**, heartbeat, retrain, weekly report.
- **Webhook**: Cron hits `/cron/scan` every minute; optionally hit `/cron/session-end` at 11:00 EST (or set `RTH_END`) to disconnect the live feed. No in-process job_queue; times come from config where used.

## Config → consumers

| Config | Used by |
|--------|--------|
| **DATA_DIR, TRADE_DATA_JSON, BOT_STATE_JSON** | `config.py` defines them; `bot/commands.py` loads/saves state and trade data (get_state, save_trade_state, _load_trade_data, _load_persisted_state). |
| **MNQ_DATA_DIR** | Sets DATA_DIR so persistence (trade_data.json, bot_state.json) survives restarts (e.g. Railway volume). |
| **PREMARKET_START, RTH_END, TRADE_SESSION_*_EST** | `bot/scheduler.py` (in_scan_window, in_trade_window); `main.py` (_parse_session_end_time); `strategy/entry_checklist.py` (in_trading_window). |
| **DAILY_SUMMARY_HOUR** | `main.py` (daily summary job time); `run_bot_pa.py` (when to run daily summary inside _run_scan_with_fresh_bot: `now.hour == DAILY_SUMMARY_HOUR and now.minute < 2`). |
| **SKIP_MONDAY, SKIP_CPI_DAYS, SKIP_FOMC_DAYS, SKIP_NFP_DAYS** | `main.run_scan` passes to `news_filter.should_trade_today()`; no trade today → single "NO TRADE TODAY" Telegram. |
| **INITIAL_BALANCE** | `config.py`; `bot/commands.py` (format_welcome_message, cmd_balance). Balance = initial_balance + total_pnl; initial_balance persisted in bot_state.json. |
| **SHOW_SCAN_STATUS, SCAN_STATUS_INTERVAL_MINUTES** | `main.py` (_send_scan_status throttle and visibility). |
| **TELEGRAM_CHAT_IDS, TELEGRAM_BOT_TOKEN** | All Telegram sends; run_bot_pa uses TELEGRAM_BOT_TOKEN for webhook and Bot(). |

## State and persistence

- **get_state()** returns in-memory `_bot_state` (bot/commands.py). It is merged at import time from **BOT_STATE_JSON** (risk, contracts, initial_balance) and **TRADE_DATA_JSON** (trade_history, active_trades, daily_pnl, trades_today, total_pnl, last_trade_date).
- **save_trade_state()** writes **TRADE_DATA_JSON** (and keeps total_pnl in memory). **BOT_STATE_JSON** is written by _save_persisted_state() when risk/contracts/initial_balance change.
- **maybe_reset_daily()** (called at start of run_scan) resets trades_today/daily_pnl when a new day (EST) is detected; then save_trade_state().

## Feed and session

- **start_live_feed_session** / **end_live_feed_session** (data/feed.py): use config BROKER, USE_LIVE_FEED, PRICE_API_URL; start/stop WebSocket (Yahoo) or Tradovate MD if present.
- **main.run_scan**: inside scan window, calls start_live_feed_session (in executor). **main** also schedules **session_end_feed_job** at RTH_END to call end_live_feed_session.
- **run_bot_pa**: `/cron/session-end` calls end_live_feed_session(); no in-process timer — use external cron at 11:00 EST (or RTH_END).

## Strategy and scan flow

- **main.run_scan** → should_trade_today (news_filter) → in_scan_window (scheduler) → start_live_feed_session → _run_scan_fetch_sync → in_trade_window → _run_single_strategy.
- **_run_single_strategy** uses **strategy**: detect_setup, validate_entry (orderflow_summary=None), ML filter, format_trade_alert, send_telegram_all; state updates and save_trade_state().
- **validate_entry** (strategy/entry_checklist.py) accepts orderflow_summary=None; check_orderflow returns None when no summary (no OF check).

## Bot commands and dashboard

- **register_commands** (bot/commands.py) registers all handlers; uses get_state(), save_trade_state(), format_welcome_message(), config (TELEGRAM_CHAT_IDS, MAX_TRADES_PER_DAY, etc.).
- **Dashboard** (dashboard/app.py): imports get_state from bot.commands; reads same JSONs via same DATA_DIR when run (e.g. `python -m dashboard.app`). For same data as bot, run on same host or point MNQ_DATA_DIR to shared path.

## Fixes applied

1. **main.py**: Daily summary job was hardcoded `time(11, 0)`. It now uses **DAILY_SUMMARY_HOUR** from config so `MNQ_DAILY_SUMMARY_HOUR` is respected.
2. **scripts/check_orderflow.py**: Script imported `main._fetch_orderflow_summary`, which was removed. Script now handles missing symbol and exits without crashing, with a short message that order flow is not used by the bot.

## Optional / legacy

- **REALTIME_ORDERFLOW_ENABLED**, **ALPACA_***, **FINNHUB_***: Used only in main._start_realtime_collectors() (polling startup). No impact on run_scan or run_bot_pa scan path.
- **Order flow**: Strategy and main no longer fetch or pass order flow; validate_entry(orderflow_summary=None). Config ORDERFLOW_* and USE_ORDERFLOW remain for any future or external use.
