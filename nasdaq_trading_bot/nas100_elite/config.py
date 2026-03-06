"""
NAS100 Elite — Non-negotiable targets, market structure, sessions, circuit breakers.
"""

# === NON-NEGOTIABLE TARGETS (all 5 simultaneously) ===
TARGETS = {
    "win_rate_pct_min": 70.0,
    "monthly_return_pct_min": 40.0,
    "max_drawdown_pct_max": 15.0,
    "profit_factor_min": 2.0,
    "signals_per_day_min": 1.0,
}

# === INSTRUMENT ===
ASSET_NAME = "NAS100"
ASSET_DISPLAY = "NAS100 (NASDAQ 100 CFD)"
POINT_VALUE_PER_LOT = 1.0  # $1 per point per 1 lot
LEVERAGE = 20  # 1:20 minimum; 1:50 recommended
AVG_DAILY_RANGE_POINTS = (150, 400)

# === SESSIONS (EST) — avoid Asian 00:00–07:00 ===
SESSION_WINDOWS = {
    "premarket": (8, 0, 9, 30),
    "orb_form": (9, 30, 9, 45),
    "ny_morning": (9, 45, 11, 30),
    "lunch": (11, 30, 13, 0),
    "ny_afternoon": (13, 0, 15, 30),
    "avoid_final": (15, 30, 16, 0),
}

# === SL/TP RULES (points) ===
SL_POINTS_MIN = 20
SL_POINTS_MAX = 80
ORB_SL_BUFFER_POINTS = 10
OB_SL_BEYOND_POINTS = (10, 20)
KEY_LEVEL_SL_BEYOND_POINTS = 20
TRAIL_POINTS_TP3 = 30
MIN_RR = 2.0

# === CONFLUENCE: need >= 5/7 to enter ===
CONFLUENCE_MIN_TO_ENTER = 5
RISK_PCT_BY_SCORE = {7: 2.0, 6: 1.5, 5: 1.0}

# === CIRCUIT BREAKERS (drawdown protection) ===
CIRCUIT_BREAKERS = {
    "daily_loss_pct_max": 3.0,
    "weekly_loss_pct_max": 8.0,
    "monthly_loss_pct_max": 15.0,
    "consecutive_losses_pause": 3,
    "consecutive_losses_stop_week": 5,
    "pause_hours_after_consec": 2,
}

# === BACKTEST ===
MIN_BACKTEST_DAYS = 90
MIN_TRADES_FOR_SUCCESS = 60
MIN_MONTHS_FOR_MONTHLY_RETURN = 2
