# MNQ Trading Bot – Riley Coleman Strategy

Fully automated Telegram trading bot for **Micro E-mini NASDAQ-100 (MNQ)** using a price-action reversal strategy (Riley Coleman style). Sends real-time trade alerts to Telegram and optionally auto-executes via broker API.

## Features

- **Indicator-free price action**: Candlestick patterns, market structure, key levels only.
- **Two setups**: Retest Reversal and Failed Breakout Reversal on 1m at key zones.
- **Key levels**: Previous day H/L/C, 7 AM candle, session opening range (9:30–9:35), round numbers.
- **Trade management**: Stop loss, 2:1+ R/R, partial exit at Target 1, breakeven and trailing alerts.
- **Trailing alerts**: Real-time Telegram messages at +1R, +1.5R, +2R, etc., with exact new stop price.
- **Safety**: Daily loss limit, max 3 trades/day, news filter, session window only.

## Requirements

- Python 3.10+
- See `requirements.txt`

## Setup

1. **Clone / copy** the `mnq_bot` folder.

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure** `config.py` (or use env vars):
   - `TELEGRAM_BOT_TOKEN` – from [@BotFather](https://t.me/BotFather)
   - `TELEGRAM_CHAT_ID` – your channel or group ID
   - `MAX_RISK_PER_TRADE_USD`, `DEFAULT_CONTRACTS`, session times, etc.

4. **Run**
   ```bash
   cd mnq_bot
   python main.py
   ```

## Telegram Commands

| Command | Description |
|--------|-------------|
| `/start` | Activate and begin scanning |
| `/stop` or `/pause` | Pause scanning and alerts |
| `/status` | Current status, active trades, P&L |
| `/levels` | Today's key price levels |
| `/pnl` | Daily/weekly P&L summary |
| `/risk [amount]` | Set max risk per trade ($) |
| `/contracts [n]` | Set MNQ contracts per trade |
| `/session [on\|off]` | Toggle session scanning |
| `/history` | Last 10 trade results |
| `/trail [on\|off]` | Trailing alerts on/off |
| `/trailmode [auto\|alert]` | Auto-move stop vs alert only |
| `/help` | List all commands |

## Configuration

- **Broker**: `BROKER = "paper"` (default), `"tradovate"`, or `"ninjatrader"`.
- **Auto-execute**: `AUTO_EXECUTE = False` – set `True` only after testing in paper mode.
- **Sessions**: 7:00–9:30 AM EST (pre-market), 9:30–11:00 AM EST (RTH).
- **Trailing**: `TRAIL_MODE = "alert"` (notify only) or `"auto"` (move stop in broker).
- **Auto-retrain**: `AUTO_RETRAIN_ENABLED = True` – strategy retrains weekly (default Sunday 8 PM EST). Configure `RETRAIN_DAY_OF_WEEK`, `RETRAIN_HOUR_EST`, `RETRAIN_MINUTE_EST`. Restart bot to apply new params after retrain.

## File Structure

```
mnq_bot/
├── main.py              # Entry point, Telegram + scan + trailing
├── config.py            # Settings
├── bot/
│   ├── commands.py      # Telegram command handlers
│   ├── alerts.py        # Alert message formatting and send
│   └── scheduler.py     # Session timing helpers
├── strategy/
│   ├── market_structure.py  # Swing high/low, trend
│   ├── key_levels.py        # Prev day, 7AM, session range, round numbers
│   ├── setups.py            # Retest & failed breakout detection
│   ├── entry_checklist.py   # Validates all entry conditions
│   └── trade_manager.py     # SL, TP, breakeven, trail milestones
├── broker/
│   ├── base.py
│   ├── paper_trade.py
│   ├── tradovate.py        # Stub – implement with real API
│   └── ninjatrader.py      # Stub – implement with ATI
├── data/
│   ├── feed.py             # 1m/15m data (mock by default)
│   └── calendar.py         # Economic news filter
├── utils/
│   ├── risk_calculator.py
│   └── logger.py
└── requirements.txt
```

## Market Data & Brokers

- **Data**: Default is **Yahoo Finance** (NQ=F) via `USE_LIVE_FEED=True`. For minimal delay, run the **Price API** (see below) and set `PRICE_API_URL`. Or use mock: `USE_LIVE_FEED=False`. Replace with NinjaTrader, IB, Tradovate, or Alpaca in `data/feed.py` for broker data.
- **Execution**: `broker/paper_trade.py` is fully functional for simulation. `tradovate.py` and `ninjatrader.py` are stubs – implement with your broker’s API before live trading.

## Price API (optional – minimal delay)

The bot can use a **local Price API** that caches Yahoo data so repeated requests don’t add delay:

1. **Start the API** (in a separate terminal):
   ```bash
   python -m api.price_server
   ```
   Server runs at `http://127.0.0.1:5001` (set `MNQ_PRICE_API_PORT` to change).

2. **Point the bot at it** in `config.py` or env:
   ```bash
   set MNQ_PRICE_API_URL=http://127.0.0.1:5001
   ```
   Or in `config.py`: `PRICE_API_URL = "http://127.0.0.1:5001"`.

3. **Run the bot** as usual; it will use the API for price and candles. The API backend is Yahoo (free); replace the fetch logic in `api/price_server.py` with a real-time source (broker/CME) when available.

Endpoints: `GET /price`, `GET /candles/1m?count=100`, `GET /candles/15m?count=50`, `GET /health`.

## Live Order Flow API (optional – zero delay when you feed trades)

The strategy can **track live order flow** (delta, buy/sell imbalance) and require it to confirm direction before entry.

1. **Start the Order Flow API** (default port 5002):
   ```bash
   python -m api.orderflow_server
   ```
   Set `MNQ_ORDERFLOW_PORT` / `MNQ_ORDERFLOW_HOST` to change.

2. **Zero delay**: Feed trades from your real-time source (Tradovate, Rithmic, Sierra Chart, etc.) via **POST**:
   ```bash
   curl -X POST http://127.0.0.1:5002/orderflow/push -H "Content-Type: application/json" -d "{\"price\": 20100.5, \"size\": 2, \"side\": \"buy\"}"
   ```
   The bot reads `GET /orderflow/summary` (session delta, imbalance) and uses it in the entry checklist when `USE_ORDERFLOW=True`.

3. **Config**: `USE_ORDERFLOW = True`, `ORDERFLOW_API_URL = "http://127.0.0.1:5002"`. Optional: `ORDERFLOW_MIN_IMBALANCE_LONG`, `ORDERFLOW_MAX_IMBALANCE_SHORT`, `ORDERFLOW_STALE_SEC`.

4. **Testing without a feed**: Run with `MNQ_ORDERFLOW_SIMULATE=true` to use a candle-based proxy (has delay; for testing only).

Endpoints: `GET /orderflow/summary`, `POST /orderflow/push`, `GET /orderflow/health`.

### Free minimal-delay price – Yahoo WebSocket (no API key)

**Default:** Yahoo WebSocket (free, no API key). The bot streams **QQQ** (Nasdaq-100 ETF) from Yahoo Finance’s WebSocket and scales it to an NQ-equivalent price.

1. **Config** (defaults on): `USE_YAHOO_WS_REALTIME = True`, `YAHOO_WS_QQQ_TO_NQ_RATIO = 50`.
2. **Run the bot** – it uses Yahoo WebSocket for current price (minimal delay) and Yahoo REST for 1m/15m candles.
3. **Optional – Price API:** Run `python -m api.price_server`. Our API streams Yahoo WS and serves `GET /price` with NQ-equivalent (`"realtime": true`). Set `MNQ_PRICE_API_URL=http://127.0.0.1:5001` to use it.

No Alpaca/Tradovate, no API keys.

### Delay-free (real-time) price – Tradovate (requires account)

If you have a **Tradovate** account with market data:

1. **Config**: `BROKER = "tradovate"`, `TRADOVATE_USE_REALTIME_MD = True`, and set `TRADOVATE_NAME`, `TRADOVATE_PASSWORD`, `TRADOVATE_APP_ID`, `TRADOVATE_APP_VERSION`, `TRADOVATE_CID`, `TRADOVATE_SEC` (or `TRADOVATE_ACCESS_TOKEN`).
2. The bot will use Tradovate WebSocket for NQ/MNQ price (delay-free) and Yahoo for candles.

## Safety (Hard-coded)

- Daily loss limit: trading stops if daily loss exceeds `MAX_DAILY_LOSS_USD`.
- Max 3 trades per day.
- No entries within 15 minutes of high-impact news (when calendar is enabled).
- No entries outside 7:00–11:00 AM EST.
- Entries only on **closed** 1m candle.
- Slippage: trades flagged if fill is more than 5 ticks from expected.

## Backtest

**Live market data (free – Yahoo Finance):**

```bash
cd mnq_bot
pip install yfinance
python run_backtest.py --live --balance 50000 --risk 75
```

Uses **Yahoo Finance** (NQ=F, ^NDX, or ES=F) 1m/15m for the last **7 days**, session 7:00–11:00 EST. No API key. If `--live` fails (e.g. Yahoo rate limit), retry later or use synthetic data.

**Synthetic data (offline):**

```bash
python run_backtest.py --balance 50000 --risk 75 --days 30
```

Options:

- `--live` – Use live data from Yahoo Finance (NQ=F, last 7 days)
- `--balance 50000` – Starting equity (default 50000)
- `--risk 75` – Max risk per trade in USD (default 75)
- `--days 30` – Trading days for synthetic data (default 30)
- `--seed 42` – Random seed for synthetic data
- `--csv backtest_trades.csv` – Save all trades to a CSV file

---

## Testing

Run the full test suite (config, strategy, data, broker, backtest, bot):

```bash
cd mnq_bot
python run_tests.py
```

Or with unittest directly:

```bash
python -m unittest tests.test_full -v
```

---

## License

Use at your own risk. Not financial advice.
