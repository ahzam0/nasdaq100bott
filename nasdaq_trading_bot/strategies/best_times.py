"""
Best times to trade NASDAQ (NAS100/NDX).
Session windows in Eastern Time (ET).
"""

from __future__ import annotations

from datetime import time

from strategies.base import ET

# --- NY Kill Zone (best for SMC / day trading) ---
# 9:30–11:00 AM EST: clean liquidity sweeps, sharp displacements
KILL_ZONE_START = time(9, 30)
KILL_ZONE_END = time(11, 0)

# --- Full regular session ---
REGULAR_START = time(9, 30)
REGULAR_END = time(16, 0)

# --- High volatility / Power Hour ---
POWER_HOUR_START = time(15, 0)
POWER_HOUR_END = time(16, 0)

# --- Avoid: first 15–30 min (chaotic open), lunch 12:00–13:30 (lower volume) ---
AVOID_OPEN_MINUTES = 30
LUNCH_START = time(12, 0)
LUNCH_END = time(13, 30)


def in_kill_zone(ts) -> bool:
    """True if timestamp is in NY Kill Zone (9:30–11:00 AM ET)."""
    if ts is None:
        return False
    try:
        t = ts.tz_convert(ET).time() if getattr(ts, "tzinfo", None) is not None else ts.time()
    except Exception:
        t = ts.time() if hasattr(ts, "time") else ts
    return KILL_ZONE_START <= t < KILL_ZONE_END


def in_regular_session(ts) -> bool:
    """True if within regular US cash session."""
    if ts is None:
        return False
    try:
        t = ts.tz_convert(ET).time() if getattr(ts, "tzinfo", None) is not None else ts.time()
    except Exception:
        t = ts.time() if hasattr(ts, "time") else ts
    return REGULAR_START <= t < REGULAR_END
