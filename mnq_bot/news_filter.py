"""
Day and news filters for Riley Coleman strategy.
Skip Mondays, CPI, FOMC, and NFP days to avoid key-level noise and false breakouts.
"""

from __future__ import annotations

import logging
import os
from datetime import date

logger = logging.getLogger(__name__)

# FOMC meeting dates (update yearly)
FOMC_DATES_2025 = [
    "2025-01-29", "2025-03-19", "2025-05-07",
    "2025-06-18", "2025-07-30", "2025-09-17",
    "2025-10-29", "2025-12-10",
]
FOMC_DATES_2026 = [
    "2026-01-28", "2026-03-18", "2026-05-06",
    "2026-06-17", "2026-07-29", "2026-09-16",
    "2026-10-28", "2026-12-09",
]
FOMC_DATES = FOMC_DATES_2025 + FOMC_DATES_2026

# US CPI release dates (approximate; BLS typically mid-month)
CPI_DATES_2025 = [
    "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-14",
    "2025-06-11", "2025-07-10", "2025-08-13", "2025-09-10", "2025-10-10",
    "2025-11-12", "2025-12-10",
]
CPI_DATES_2026 = [
    "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-10", "2026-05-13",
    "2026-06-10", "2026-07-10", "2026-08-12", "2026-09-10", "2026-10-13",
    "2026-11-11", "2026-12-10",
]
CPI_DATES = CPI_DATES_2025 + CPI_DATES_2026


def is_monday(d: date | None = None) -> bool:
    """Monday = weekday 0."""
    d = d or date.today()
    return d.weekday() == 0


def is_nfp_friday(d: date | None = None) -> bool:
    """NFP = first Friday of every month."""
    d = d or date.today()
    if d.weekday() != 4:  # 4 = Friday
        return False
    return d.day <= 7  # first Friday always on day 1–7


def is_fomc_day(d: date | None = None) -> bool:
    d = d or date.today()
    return d.isoformat() in FOMC_DATES


def is_cpi_day(d: date | None = None) -> bool:
    """True if today is a known CPI release date (hardcoded list)."""
    d = d or date.today()
    return d.isoformat() in CPI_DATES


def check_cpi_today() -> bool:
    """
    Returns True if today is a CPI release day.
    Uses hardcoded list; optional env TRADING_ECONOMICS_API_KEY can enable API later.
    """
    if is_cpi_day():
        return True
    api_key = os.getenv("TRADING_ECONOMICS_API_KEY", "").strip()
    if not api_key:
        return False
    try:
        import requests
        today = date.today().isoformat()
        url = (
            "https://api.tradingeconomics.com/calendar/country/united%20states"
            f"?c={api_key}&d1={today}&d2={today}"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        events = resp.json()
        for ev in events:
            event_name = (ev.get("Event") or "").upper()
            importance = (ev.get("Importance") or "").upper()
            if "CPI" in event_name and importance == "HIGH":
                return True
        return False
    except Exception as e:
        logger.debug("CPI calendar check failed: %s", e)
        return False


def should_trade_today(
    skip_monday: bool = True,
    skip_cpi: bool = True,
    skip_fomc: bool = True,
    skip_nfp: bool = True,
    d: date | None = None,
) -> tuple[bool, str]:
    """
    Returns (True, reason) if safe to trade today, (False, reason) if should skip.
    """
    d = d or date.today()
    if skip_monday and is_monday(d):
        return False, "Monday — skipping per Riley Coleman rule"
    if skip_fomc and is_fomc_day(d):
        return False, "FOMC day — key levels unreliable"
    if skip_nfp and is_nfp_friday(d):
        return False, "NFP Friday — false breakouts everywhere"
    if skip_cpi and check_cpi_today():
        return False, "CPI release day — skipping"
    return True, "Safe to trade today"
