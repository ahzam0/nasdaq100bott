"""
NASDAQ trading calendar, earnings proximity, economic events, OpEx, triple witching.
Uses exchange-calendars for NASDAQ schedule; earnings/economic from config + optional APIs.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# NASDAQ Trading Calendar (exchange-calendars)
# ---------------------------------------------------------------------------


class NASDAQCalendar:
    """NASDAQ exchange trading days and sessions (ET)."""

    def __init__(self) -> None:
        self._calendar = None
        self._load()

    def _load(self) -> None:
        try:
            import exchange_calendars as xcals
            self._calendar = xcals.get_calendar("NASDAQ")
        except Exception as e:
            logger.warning("exchange_calendars not available: %s. Using fallback.", e)
            self._calendar = None

    def is_open(self, dt: datetime | date) -> bool:
        """True if NASDAQ is open for trading on this date/time."""
        if self._calendar is None:
            d = dt.date() if isinstance(dt, datetime) else dt
            return d.weekday() < 5  # Mon–Fri fallback
        if isinstance(dt, datetime):
            dt = dt.astimezone(ET)
            return self._calendar.is_open_on_minute(dt)
        return self._calendar.is_session(dt)

    def next_open(self, dt: datetime) -> datetime:
        """Next opening minute after dt (ET)."""
        if self._calendar is None:
            d = dt.date()
            while d.weekday() >= 5:
                d += timedelta(days=1)
            return datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)
        return self._calendar.next_open(dt).astimezone(ET)

    def session_open(self, d: date) -> datetime:
        """9:30 AM ET session open for date d."""
        return datetime(d.year, d.month, d.day, 9, 30, tzinfo=ET)

    def session_close(self, d: date) -> datetime:
        """4:00 PM ET session close for date d."""
        return datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET)

    def premarket_open(self, d: date) -> datetime:
        """4:00 AM ET pre-market."""
        return datetime(d.year, d.month, d.day, 4, 0, tzinfo=ET)

    def after_hours_close(self, d: date) -> datetime:
        """8:00 PM ET after-hours close."""
        return datetime(d.year, d.month, d.day, 20, 0, tzinfo=ET)


# Singleton
_nasdaq_cal: Optional[NASDAQCalendar] = None


def get_nasdaq_calendar() -> NASDAQCalendar:
    global _nasdaq_cal
    if _nasdaq_cal is None:
        _nasdaq_cal = NASDAQCalendar()
    return _nasdaq_cal


# ---------------------------------------------------------------------------
# Earnings proximity (stub: extend with Polygon/Alpha Vantage/Nasdaq API)
# ---------------------------------------------------------------------------

# In production: fetch from Polygon earnings calendar or nasdaq-data-link
# Format: { symbol: [date, date, ...] }
_EARNINGS_CACHE: dict[str, list[date]] = {}
_CACHE_LOADED = False


def _load_earnings_cache() -> None:
    global _CACHE_LOADED
    if _CACHE_LOADED:
        return
    # Optional: load from data/earnings_dates.json or API
    import os
    p = os.path.join(os.path.dirname(__file__), "earnings_dates.json")
    if os.path.isfile(p):
        try:
            import json
            with open(p, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for sym, dates in raw.items():
                _EARNINGS_CACHE[sym.upper()] = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
        except Exception as e:
            logger.debug("Could not load earnings cache: %s", e)
    _CACHE_LOADED = True


def get_earnings_within_days(
    symbols: list[str],
    as_of: date | None = None,
    within_days: int = 5,
) -> dict[str, list[date]]:
    """Return { symbol: [earnings_date, ...] } for symbols with earnings in the next `within_days`."""
    _load_earnings_cache()
    as_of = as_of or date.today()
    end = as_of + timedelta(days=within_days)
    out: dict[str, list[date]] = {}
    for sym in symbols:
        sym = sym.upper()
        dates = _EARNINGS_CACHE.get(sym, [])
        in_range = [d for d in dates if as_of <= d <= end]
        if in_range:
            out[sym] = sorted(in_range)
    return out


def is_earnings_soon(symbol: str, within_days: int = 5, as_of: date | None = None) -> bool:
    """True if symbol has earnings in the next `within_days`."""
    d = get_earnings_within_days([symbol], as_of=as_of, within_days=within_days)
    return symbol.upper() in d and len(d[symbol.upper()]) > 0


# ---------------------------------------------------------------------------
# Economic events (FOMC, CPI, NFP, PCE, PPI)
# ---------------------------------------------------------------------------

# High-impact US economic release dates (example: extend with API or CSV)
# Format: list of (date, "FOMC"|"CPI"|"NFP"|"PCE"|"PPI")
_ECONOMIC_DATES: list[tuple[date, str]] = []


def _load_economic_dates() -> None:
    global _ECONOMIC_DATES
    if _ECONOMIC_DATES:
        return
    # FOMC: 8 meetings/year (example 2023–2024)
    fomc_2023 = [date(2023, 2, 1), date(2023, 3, 22), date(2023, 5, 3), date(2023, 6, 14),
                 date(2023, 7, 26), date(2023, 9, 20), date(2023, 11, 1), date(2023, 12, 13)]
    fomc_2024 = [date(2024, 1, 31), date(2024, 3, 20), date(2024, 5, 1), date(2024, 6, 12),
                 date(2024, 7, 31), date(2024, 9, 18), date(2024, 11, 7), date(2024, 12, 18)]
    for d in fomc_2023 + fomc_2024:
        _ECONOMIC_DATES.append((d, "FOMC"))
    # Add more from config or API
    _ECONOMIC_DATES.sort(key=lambda x: x[0])


def get_economic_events(
    from_date: date,
    to_date: date,
    event_types: list[str] | None = None,
) -> list[tuple[date, str]]:
    """Events in [from_date, to_date]. event_types e.g. ['FOMC','CPI','NFP'] or None for all."""
    _load_economic_dates()
    out = [(d, t) for d, t in _ECONOMIC_DATES if from_date <= d <= to_date]
    if event_types:
        out = [(d, t) for d, t in out if t in event_types]
    return out


def is_fomc_day(d: date | None = None) -> bool:
    """True if d is an FOMC meeting day."""
    d = d or date.today()
    events = get_economic_events(d, d, event_types=["FOMC"])
    return any(e[0] == d for e in events)


def is_day_before_fomc(d: date | None = None) -> bool:
    """True if next calendar day is FOMC."""
    d = d or date.today()
    return is_fomc_day(d + timedelta(days=1))


# ---------------------------------------------------------------------------
# Options expiration (weekly Friday; monthly 3rd Friday)
# ---------------------------------------------------------------------------


def friday_of_week(d: date) -> date:
    """Friday of the week containing d."""
    w = d.weekday()
    return d + timedelta(days=(4 - w) % 7)


def third_friday(year: int, month: int) -> date:
    """Third Friday of month (monthly OpEx)."""
    first = date(year, month, 1)
    # first weekday of month; then add 2 weeks to get to 3rd week
    w = first.weekday()
    first_friday = first + timedelta(days=(4 - w) % 7)
    if first_friday.day <= 7:
        third_fri = first_friday + timedelta(days=14)
    else:
        third_fri = first_friday + timedelta(days=7)
    return third_fri


def is_opex_week(d: date | None = None) -> bool:
    """True if d is in a week containing monthly options expiration (3rd Friday)."""
    d = d or date.today()
    third = third_friday(d.year, d.month)
    fri = friday_of_week(d)
    return fri == third


def is_triple_witching(d: date | None = None) -> bool:
    """True if d is 3rd Friday of Mar/Jun/Sep/Dec (triple witching)."""
    d = d or date.today()
    if d.month not in (3, 6, 9, 12):
        return False
    return d == third_friday(d.year, d.month)


# ---------------------------------------------------------------------------
# NASDAQ-100 rebalance (quarterly: 3rd Fri Dec, Mar, Jun, Sep — not exact; NDX spec)
# ---------------------------------------------------------------------------


def is_nasdaq_rebalance_week(d: date | None = None) -> bool:
    """True if week is near NASDAQ-100 quarterly rebalance (approximate)."""
    d = d or date.today()
    # Typically after 3rd Friday of Dec/Mar/Jun/Sep
    if d.month not in (12, 3, 6, 9):
        return False
    third = third_friday(d.year, d.month)
    return 0 <= (d - third).days <= 7
