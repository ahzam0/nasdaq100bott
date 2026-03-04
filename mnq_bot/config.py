"""
MNQ Trading Bot – Riley Coleman Strategy
Configuration settings. Never commit real API keys.
"""

import os
from pathlib import Path

# Load .env from project root so TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID work when starting from any cwd
BASE_DIR = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

# Paths
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
JOURNAL_PATH = BASE_DIR / "trade_journal.csv"
DB_PATH = BASE_DIR / "mnq_bot_state.db"
BOT_STATE_JSON = BASE_DIR / "data" / "bot_state.json"  # Persist risk, contracts

# Telegram (use env vars in production; never commit real tokens)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip() or None

# Trading – previous strategy (~40% monthly return, BACKTEST_3M_RESULT.md)
INSTRUMENT = "MNQ"
TICK_VALUE_USD = 2.0  # 1 point = $2/contract on MNQ
MAX_RISK_PER_TRADE_USD = 420
MAX_DAILY_LOSS_USD = 700       # Allow room for 2 full losses per day
DEFAULT_CONTRACTS = 1
MIN_RR_RATIO = 1.85
PARTIAL_EXIT_PERCENT = 50
SLIPPAGE_TICKS = 5  # Flag trade if fill is more than this from expected

# Sessions (EST) – 7:00–11:00 scan window (previous strategy)
PREMARKET_START = os.getenv("MNQ_PREMARKET_START", "07:00").strip()
PREMARKET_END = "09:30"
RTH_START = "09:30"
RTH_END = os.getenv("MNQ_RTH_END", "11:00").strip()
SESSION_OPENING_RANGE_MINUTES = 5  # 9:30–9:35
SCAN_ACTIVE = True
SHOW_SCAN_STATUS = os.getenv("MNQ_SHOW_SCAN_STATUS", "true").lower() in ("1", "true", "yes")
DAILY_SUMMARY_HOUR = int(os.getenv("MNQ_DAILY_SUMMARY_HOUR", "11"))  # Send daily summary (EST)

# Strategy – previous (Retest only, trend only, ~40% return)
MAX_TRADES_PER_DAY = 2
NEWS_BUFFER_MINUTES = 15
SWING_LOOKBACK_15M = 10  # Last N candles on 15-min for swing detection
ROUND_NUMBER_STEP = 50   # e.g. 19000, 19050, 19100
LEVEL_TOLERANCE_PTS = 8.0
REQUIRE_TREND_ONLY = True   # Only trade when 15m trend is Bullish/Bearish (not Ranging)
RETEST_ONLY = True
SKIP_FIRST_MINUTES = 5
NO_LONG_FIRST_MINUTES_RTH = int(os.getenv("MNQ_NO_LONG_FIRST_MIN_RTH", "0"))
NO_SHORT_FIRST_MINUTES_RTH = int(os.getenv("MNQ_NO_SHORT_FIRST_MIN_RTH", "0"))
MIN_BODY_PTS = 0.0   # Original: 51.9% WR, 35.46% return, 54 trades (3mo)
MAX_RISK_PTS = 350.0

# Minimum 1 trade per day (highly winnable): after this many minutes from 7:00 EST, if 0 trades, use relaxed min R:R once
TARGET_MIN_TRADES_PER_DAY = 1
FALLBACK_AFTER_MINUTES = 120  # 9:00 EST - use fallback min R:R if still 0 trades (earlier = more chance for 1/day)
FALLBACK_MIN_RR = 1.7         # Slightly relaxed R:R for “best available” 1 trade (still quality)

# Auto-retrain: run train_for_live on a schedule and update config (run in background)
AUTO_RETRAIN_ENABLED = os.getenv("MNQ_AUTO_RETRAIN", "true").lower() in ("1", "true", "yes")
RETRAIN_DAY_OF_WEEK = int(os.getenv("MNQ_RETRAIN_DAY", "0"))   # 0=Sunday, 1=Monday, ... 6=Saturday (PTB v20+)
RETRAIN_HOUR_EST = int(os.getenv("MNQ_RETRAIN_HOUR", "20"))    # Hour (0-23) EST
RETRAIN_MINUTE_EST = int(os.getenv("MNQ_RETRAIN_MINUTE", "0")) # Minute

# Trailing Profit System
TRAIL_ALERTS_ENABLED = True
TRAIL_MODE = "alert"  # "alert" | "auto"
TRAIL_MILESTONES = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
TRAIL_AFTER_5R_TICKS = 10
PRICE_PULLBACK_ALERT_THRESHOLD = 0.5  # Alert when price pulls back 0.5R from high

# Broker: "ninjatrader" | "tradovate" | "paper"
BROKER = os.getenv("MNQ_BROKER", "paper")
# Data feed: True = live price from Yahoo Finance (NQ=F, free). False = MockDataFeed (synthetic).
USE_LIVE_FEED = os.getenv("MNQ_USE_LIVE_FEED", "true").lower() in ("1", "true", "yes")
# If set, bot uses our Price API (run: python -m api.price_server). Cached; minimal delay. Example: http://127.0.0.1:5001
PRICE_API_URL = os.getenv("MNQ_PRICE_API_URL", "").strip() or None
# Live order flow: own API (run: python -m api.orderflow_server). Feed trades via POST /orderflow/push for zero delay.
USE_ORDERFLOW = os.getenv("MNQ_USE_ORDERFLOW", "false").lower() in ("1", "true", "yes")
ORDERFLOW_API_URL = os.getenv("MNQ_ORDERFLOW_API_URL", "http://127.0.0.1:5002").strip()
ORDERFLOW_REQUIRE_CONFIRM = True   # Require order flow to confirm direction (delta/imbalance)
ORDERFLOW_MIN_IMBALANCE_LONG = 0.0   # Min imbalance_ratio for LONG (-1 to 1). 0 = any, 0.2 = slight buy bias
ORDERFLOW_MAX_IMBALANCE_SHORT = 0.0  # Max imbalance_ratio for SHORT (e.g. 0 = neutral/sell, -0.2 = require sell bias)
ORDERFLOW_STALE_SEC = 30.0   # If summary older than this, skip order flow check (allow entry)
AUTO_EXECUTE = False

# NinjaTrader (when BROKER = "ninjatrader")
NINJATRADER_ATI_HOST = "localhost"
NINJATRADER_ATI_PORT = 36973

# Tradovate (when BROKER = "tradovate")
TRADOVATE_API_URL = "https://api.tradovate.com/v1"
TRADOVATE_DEV_KEY = os.getenv("TRADOVATE_DEV_KEY", "")
TRADOVATE_ACCESS_TOKEN = os.getenv("TRADOVATE_ACCESS_TOKEN", "")
# Real-time (delay-free) market data via Tradovate WebSocket. Requires Tradovate account with market data.
TRADOVATE_USE_REALTIME_MD = os.getenv("MNQ_TRADOVATE_REALTIME", "false").lower() in ("1", "true", "yes")
TRADOVATE_NAME = os.getenv("TRADOVATE_NAME", "")
TRADOVATE_PASSWORD = os.getenv("TRADOVATE_PASSWORD", "")
TRADOVATE_APP_ID = os.getenv("TRADOVATE_APP_ID", "")
TRADOVATE_APP_VERSION = os.getenv("TRADOVATE_APP_VERSION", "1.0")
TRADOVATE_CID = os.getenv("TRADOVATE_CID", "0")
TRADOVATE_SEC = os.getenv("TRADOVATE_SEC", "")
TRADOVATE_DEMO = os.getenv("TRADOVATE_DEMO", "true").lower() in ("1", "true", "yes")
TRADOVATE_MD_SYMBOL = os.getenv("TRADOVATE_MD_SYMBOL", "NQ")  # NQ or MNQ

# Alpaca (optional – when BROKER = "paper" with live data)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"  # or live

# Free minimal-delay price: Yahoo WebSocket (QQQ stream -> NQ equivalent). No API key.
USE_YAHOO_WS_REALTIME = os.getenv("MNQ_YAHOO_WS_REALTIME", "true").lower() in ("1", "true", "yes")
YAHOO_WS_QQQ_TO_NQ_RATIO = float(os.getenv("YAHOO_WS_QQQ_TO_NQ_RATIO", "41.15"))  # NQ = QQQ * this (calibrated ~24,565)

# Economic calendar (Forex Factory or similar)
ECONOMIC_CALENDAR_URL = "https://www.forexfactory.com/calendar"
USE_ECONOMIC_CALENDAR = True
# Optional: manual high-impact times today (EST) as "HH:MM" if parser fails. E.g. ["8:30", "10:00"]
CALENDAR_MANUAL_HIGH_IMPACT_TIMES = os.getenv("MNQ_CALENDAR_MANUAL_TIMES", "").strip().split() or []

# Logging
LOG_LEVEL = "INFO"
LOG_TRADES = True
