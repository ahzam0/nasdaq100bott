"""
NAS100 v3.0 — Targets unchanged. Risk table and circuit breakers per v3 spec.
NO 5/7 confluence gate. Simple 2–3 condition rules only.
"""

# === TARGETS (all 5 must be met) ===
TARGETS = {
    "signals_per_day_min": 1.0,
    "win_rate_pct_min": 70.0,
    "monthly_return_pct_min": 40.0,
    "profit_factor_min": 2.0,
    "max_drawdown_pct_max": 15.0,
}

# === RISK TABLE (v3) ===
# First trade of day: 1.5%, second: 1.0%, third: 0.5%. Max 3/day.
RISK_TABLE = {
    "first_trade_pct": 1.5,
    "second_trade_pct": 1.0,
    "third_trade_pct": 0.5,
    "max_trades_per_day": 3,
}

# === CIRCUIT BREAKERS v3 ===
CIRCUIT_BREAKERS_V3 = {
    "daily_loss_pct_stop": 2.0,
    "weekly_loss_pct_stop": 6.0,
    "monthly_loss_pct_stop": 12.0,
}

# === STRATEGY A — EMA pullback ===
EMA_TREND_SEPARATION_PTS = 5.0  # EMAs within 5 pts = no trade
SL_BEYOND_PULLBACK_WICK_PTS = 10
TP1_RR = 1.0
TP2_RR = 2.0
TP3_RR = 3.0
TP3_TRAIL_PTS = 20

# === STRATEGY B — ORB ===
ORB_SL_BUFFER_PTS = 10
# For ^NDX (index ~20k), daily range often 200–500 pts; keep max high so we get signals
ORB_RANGE_MAX_PTS = 2000
ORB_RANGE_MIN_PTS = 15

# === STRATEGY C — PDH/PDL ===
PDH_PDL_SL_PTS = 15
PDH_PDL_TP1_PTS = 40
PDH_PDL_TP2_PTS = 80
PDH_PDL_TRAIL_PTS = 30
PDH_PDL_SKIP_MOVE_PTS = 500  # skip if price already moved >500 from prev close (^NDX scale)

# === BACKTEST v3 ===
MIN_BACKTEST_DAYS = 60
MIN_TRADES = 40
SPREAD_PTS = 1
SLIPPAGE_PTS = 2
POINT_VALUE = 1.0  # $1 per point per lot
