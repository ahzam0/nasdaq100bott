# MNQ Bot – Deployment Readiness

## Is the bot fully ready to deploy?

**Yes, for alert-only / paper-trading deployment.** Use the checklist below for your environment.

| Use case | Ready? | Notes |
|----------|--------|--------|
| **Telegram alerts only** (no live execution) | ✅ Yes | Set Telegram env vars, run `python main.py`. Alerts + trailing + daily summary work. |
| **Paper trading** (simulated fills) | ✅ Yes | `BROKER=paper`, `AUTO_EXECUTE=True` optional. Paper broker is implemented. |
| **Live execution (Tradovate/NinjaTrader)** | ⚠️ Stub | Broker modules are stubs. Implement real API/ATI calls before live money. |

---

## Pre-deploy checklist

### 1. Secrets (required)

- [ ] **TELEGRAM_BOT_TOKEN** – from [@BotFather](https://t.me/BotFather). Set via env (no default in code).
- [ ] **TELEGRAM_CHAT_ID** – your chat/channel ID. Set via env.

Example (Linux/macOS):

```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
python main.py
```

Windows (PowerShell):

```powershell
$env:TELEGRAM_BOT_TOKEN = "your_bot_token"
$env:TELEGRAM_CHAT_ID = "your_chat_id"
python main.py
```

### 2. Python & dependencies

- [ ] Python 3.10+
- [ ] `pip install -r requirements.txt`

### 3. Config (optional overrides)

- [ ] **BROKER** – `paper` (default) or `tradovate` / `ninjatrader` when implemented.
- [ ] **AUTO_EXECUTE** – `False` (default). Set `True` only after testing in paper.
- [ ] **USE_LIVE_FEED** – `true` (default) for Yahoo-based data.
- [ ] **MAX_RISK_PER_TRADE_USD**, **MAX_TRADES_PER_DAY**, **MAX_DAILY_LOSS_USD** – tune for your risk.

### 4. Data & optional services

- [ ] **Market data** – Default: Yahoo (NQ=F). For lower delay, run `python -m api.price_server` and set `MNQ_PRICE_API_URL`.
- [ ] **Order flow** – Optional. Set `MNQ_USE_ORDERFLOW=true` and run `python -m api.orderflow_server` if you use it.

### 5. Production run

- [ ] Run in a stable environment (screen, tmux, or a process manager like systemd/supervisor).
- [ ] Session window: 7:00–11:00 AM EST. Bot only scans and alerts in that window.
- [ ] Auto-retrain: weekly (default Sunday 8 PM EST). Restart bot after retrain to apply new params.

---

## What is not included

- **Persistent state** – `trades_today`, `daily_pnl`, `active_trades`, `trade_history` are in-memory. They reset on restart. For long-running production, consider persisting to `DB_PATH` (SQLite).
- **Live broker execution** – Tradovate/NinjaTrader integration is stub-only. Implement and test before using with real money.
- **HTTPS / webhook** – Bot uses polling. For very high scale, consider switching to Telegram webhooks behind HTTPS.

---

## Quick start (deploy)

```bash
cd mnq_bot
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python main.py
```

For background run (Linux): `nohup python main.py &` or use systemd/supervisor.
