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
TRADE_DATA_JSON = BASE_DIR / "data" / "trade_data.json"  # Persist trade history, active_trades, daily_pnl (survives restart)

# Telegram (use env vars in production; never commit real tokens)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or None
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip() or None
# All chat IDs that receive alerts and have full bot access.
_HARDCODED_CHAT_IDS = ["8309667442", "6336909242"]

def _telegram_chat_ids():
    raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    ids = [c.strip() for c in raw.split(",") if c.strip()] if raw else []
    for cid in _HARDCODED_CHAT_IDS:
        if cid not in ids:
            ids.append(cid)
    return ids
TELEGRAM_CHAT_IDS = _telegram_chat_ids()

# Trading – previous strategy (~40% monthly return, BACKTEST_3M_RESULT.md)
INSTRUMENT = "MNQ"
TICK_VALUE_USD = 2.0  # 1 point = $2/contract on MNQ
MAX_RISK_PER_TRADE_USD = 380
MAX_DAILY_LOSS_USD = 760       # Allow room for 2 full losses per day
DEFAULT_CONTRACTS = 1
MIN_RR_RATIO = 1.6
PARTIAL_EXIT_PERCENT = 50
SLIPPAGE_TICKS = 5  # Flag trade if fill is more than this from expected

# Session: signals only 7:00–11:00 AM EST (fixed for live bot)
SCAN_SESSION_EST = "7:00–11:00 AM EST"
PREMARKET_START = os.getenv("MNQ_PREMARKET_START", "07:00").strip() or "07:00"
PREMARKET_END = "09:30"
RTH_START = "09:30"
RTH_END = os.getenv("MNQ_RTH_END", "11:00").strip() or "11:00"
SESSION_OPENING_RANGE_MINUTES = 5  # 9:30–9:35
SCAN_ACTIVE = True
SHOW_SCAN_STATUS = os.getenv("MNQ_SHOW_SCAN_STATUS", "true").lower() in ("1", "true", "yes")
DAILY_SUMMARY_HOUR = int(os.getenv("MNQ_DAILY_SUMMARY_HOUR", "11"))  # Send daily summary (EST)

# Strategy – DEFAULT FOR LIVE SIGNALS
# Best Balanced config: 86.7% WR, +60.41% return, 2.50% DD, PF 16.47 (3-month live backtest)
MAX_TRADES_PER_DAY = 1
NEWS_BUFFER_MINUTES = 15
SWING_LOOKBACK_15M = 10  # Last N candles on 15-min for swing detection
ROUND_NUMBER_STEP = 50   # e.g. 19000, 19050, 19100
LEVEL_TOLERANCE_PTS = 6.0
REQUIRE_TREND_ONLY = False
RETEST_ONLY = True
SKIP_FIRST_MINUTES = 0
NO_LONG_FIRST_MINUTES_RTH = int(os.getenv("MNQ_NO_LONG_FIRST_MIN_RTH", "0"))
NO_SHORT_FIRST_MINUTES_RTH = int(os.getenv("MNQ_NO_SHORT_FIRST_MIN_RTH", "0"))
MIN_BODY_PTS = 2.0
MAX_RISK_PTS = 200.0
TP1_RR = 1.6
TP2_RR = 2.5

# Minimum 1 trade per day: after this many minutes from 7:00 EST, if 0 trades, use relaxed min R:R once
TARGET_MIN_TRADES_PER_DAY = 1
FALLBACK_AFTER_MINUTES = 120  # Use fallback min R:R if still 0 trades by this time
FALLBACK_MIN_RR = 1.7         # Slightly relaxed R:R for "best available" 1 trade (still quality)

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

# Alpaca Market Data API (free tier: real-time IEX trades + quotes for QQQ)
# Sign up free at https://alpaca.markets → Paper account → API keys
ALPACA_DATA_API_KEY = os.getenv("ALPACA_DATA_API_KEY", "").strip() or ALPACA_API_KEY
ALPACA_DATA_SECRET_KEY = os.getenv("ALPACA_DATA_SECRET_KEY", "").strip() or ALPACA_SECRET_KEY

# Finnhub (free tier: real-time US stock trades for QQQ)
# Sign up free at https://finnhub.io → Dashboard → API token
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "").strip()

# Real-time order flow: enable Alpaca/Finnhub WebSocket collectors for true order flow
REALTIME_ORDERFLOW_ENABLED = os.getenv("MNQ_REALTIME_ORDERFLOW", "true").lower() in ("1", "true", "yes")

# Free price: Yahoo WebSocket = minimal delay but uses threads (can fail on Railway etc.).
# Default false = live price via Yahoo REST (updated every scan, no extra threads). Set true for WebSocket if host allows.
USE_YAHOO_WS_REALTIME = os.getenv("MNQ_YAHOO_WS_REALTIME", "false").lower() in ("1", "true", "yes")
# Runtime override from /settings page (data/runtime_settings.json)
RUNTIME_SETTINGS_PATH = BASE_DIR / "data" / "runtime_settings.json"


def get_use_yahoo_ws_realtime() -> bool:
    """Current Yahoo WebSocket setting: runtime file overrides env/default."""
    try:
        if RUNTIME_SETTINGS_PATH.exists():
            import json
            data = json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8"))
            if "yahoo_ws_realtime" in data:
                return bool(data["yahoo_ws_realtime"])
    except Exception:
        pass
    return USE_YAHOO_WS_REALTIME


def set_use_yahoo_ws_realtime(enabled: bool) -> None:
    """Persist Yahoo WebSocket on/off (used by /settings page)."""
    RUNTIME_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        import json
        data = {}
        if RUNTIME_SETTINGS_PATH.exists():
            data = json.loads(RUNTIME_SETTINGS_PATH.read_text(encoding="utf-8"))
        data["yahoo_ws_realtime"] = enabled
        RUNTIME_SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        raise


YAHOO_WS_QQQ_TO_NQ_RATIO = float(os.getenv("YAHOO_WS_QQQ_TO_NQ_RATIO", "41.15"))  # NQ = QQQ * this (calibrated ~24,565)

# Economic calendar (Forex Factory or similar)
ECONOMIC_CALENDAR_URL = "https://www.forexfactory.com/calendar"
USE_ECONOMIC_CALENDAR = True
# Optional: manual high-impact times today (EST) as "HH:MM" if parser fails. E.g. ["8:30", "10:00"]
CALENDAR_MANUAL_HIGH_IMPACT_TIMES = os.getenv("MNQ_CALENDAR_MANUAL_TIMES", "").strip().split() or []

# VIX filter: block trading when VIX > threshold, reduce risk when elevated
VIX_FILTER_ENABLED = os.getenv("MNQ_VIX_FILTER", "true").lower() in ("1", "true", "yes")
VIX_BLOCK_THRESHOLD = float(os.getenv("MNQ_VIX_BLOCK", "30"))
VIX_REDUCE_THRESHOLD = float(os.getenv("MNQ_VIX_REDUCE", "25"))

# Dynamic position sizing
DYNAMIC_SIZING_ENABLED = os.getenv("MNQ_DYNAMIC_SIZING", "true").lower() in ("1", "true", "yes")
RISK_PCT_OF_EQUITY = float(os.getenv("MNQ_RISK_PCT_EQUITY", "0.75"))

# AI/ML signal filter
ML_FILTER_ENABLED = os.getenv("MNQ_ML_FILTER", "true").lower() in ("1", "true", "yes")
ML_FILTER_THRESHOLD = float(os.getenv("MNQ_ML_THRESHOLD", "0.5"))

# Web dashboard
DASHBOARD_PORT = int(os.getenv("MNQ_DASHBOARD_PORT", "5050"))

# Weekly P&L report: day and hour (EST)
WEEKLY_REPORT_DAY = int(os.getenv("MNQ_WEEKLY_REPORT_DAY", "5"))  # 5=Friday
WEEKLY_REPORT_HOUR = int(os.getenv("MNQ_WEEKLY_REPORT_HOUR", "11"))

# Multi-instrument support
INSTRUMENTS = {
    "MNQ": {"tick_value": 2.0, "symbol": "NQ=F", "round_step": 50, "name": "Micro E-mini Nasdaq"},
    "ES": {"tick_value": 12.50, "symbol": "ES=F", "round_step": 25, "name": "E-mini S&P 500"},
    "MES": {"tick_value": 1.25, "symbol": "ES=F", "round_step": 25, "name": "Micro E-mini S&P 500"},
    "NQ": {"tick_value": 20.0, "symbol": "NQ=F", "round_step": 50, "name": "E-mini Nasdaq"},
    "YM": {"tick_value": 5.0, "symbol": "YM=F", "round_step": 100, "name": "E-mini Dow"},
    "MYM": {"tick_value": 0.50, "symbol": "YM=F", "round_step": 100, "name": "Micro E-mini Dow"},
}
ACTIVE_INSTRUMENTS = [x.strip() for x in os.getenv("MNQ_ACTIVE_INSTRUMENTS", "MNQ").split(",") if x.strip()]

# Active strategy: "riley" only (Trend & Key Levels / Riley Coleman)
ACTIVE_STRATEGY = os.getenv("MNQ_ACTIVE_STRATEGY", "riley").strip().lower()

# Scalp strategy parameters (optimized: 71.4% WR, 2.43 PF, +5.65% on 7d backtest)
SCALP_MAX_TRADES_PER_DAY = int(os.getenv("MNQ_SCALP_MAX_TRADES", "4"))
SCALP_MAX_RISK_PTS = float(os.getenv("MNQ_SCALP_MAX_RISK", "40"))
SCALP_TP1_PTS = float(os.getenv("MNQ_SCALP_TP1", "30"))
SCALP_TP2_PTS = float(os.getenv("MNQ_SCALP_TP2", "80"))
SCALP_COOLDOWN_BARS = int(os.getenv("MNQ_SCALP_COOLDOWN", "2"))
SCALP_MIN_ATR = float(os.getenv("MNQ_SCALP_MIN_ATR", "15.0"))
SCALP_MOMENTUM_THRESHOLD = float(os.getenv("MNQ_SCALP_MOMENTUM", "25"))

# Smart Money System
SMART_MONEY_ENABLED = os.getenv("MNQ_SMART_MONEY", "true").lower() in ("1", "true", "yes")

# Logging
LOG_LEVEL = "INFO"
LOG_TRADES = True
