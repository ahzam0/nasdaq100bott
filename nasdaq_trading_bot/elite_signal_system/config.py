"""
Elite Signal System — Mandatory performance targets and rules.
"""

# === MANDATORY PERFORMANCE TARGETS (all must be met simultaneously) ===
TARGETS = {
    "signals_per_day_min": 1.0,
    "win_rate_pct_min": 70.0,
    "monthly_return_pct_min": 40.0,
    "profit_factor_min": 2.0,
    "max_drawdown_pct_max": 15.0,
}

# === TRADING RULES (never break) ===
MAX_RISK_PCT_PER_TRADE = 2.0
MIN_RR_RATIO = 2.0
PREFERRED_RR_RATIO = 3.0

# === BACKTEST REQUIREMENTS ===
MIN_BACKTEST_DAYS = 90
PREFERRED_BACKTEST_DAYS = 180
MIN_TRADES_FOR_CONCLUSION = 60
SPREAD_PIPS = 1.0
SLIPPAGE_PIPS = 1.5

# === OPTIMIZATION ===
MAX_OPTIMIZATION_ROUNDS_PER_STRATEGY = 3
MIN_DAYS_FOR_SUCCESS_CLAIM = 30

# === ASSETS (liquid, sufficient volatility) ===
DEFAULT_ASSETS = ["QQQ", "SPY", "AAPL", "MSFT", "NVDA", "XAUUSD"]  # XAUUSD placeholder for gold
TIMEFRAMES_ALLOWED = ["M15", "M30", "H1", "H4", "D1"]
