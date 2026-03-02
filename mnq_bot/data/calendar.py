"""
Economic calendar check: avoid entering trades within N minutes of high-impact news.
Results are cached to avoid repeated HTTP requests and delay on every entry check.
Parses Forex Factory (or uses manual times from config).
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from config import (
    NEWS_BUFFER_MINUTES,
    USE_ECONOMIC_CALENDAR,
    CALENDAR_MANUAL_HIGH_IMPACT_TIMES,
)

logger = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")

# Cache to avoid delay: one HTTP request per CALENDAR_CACHE_MINUTES max
_CALENDAR_CACHE: list[datetime] = []
_CALENDAR_CACHE_TIME: float = 0.0
CALENDAR_CACHE_MINUTES = 60


def _parse_forexfactory(html: str, today_est: datetime) -> list[datetime]:
    """
    Parse Forex Factory calendar page for high-impact events.
    Looks for table rows or spans with 'high' impact and time. Returns list of event times (EST).
    """
    events: list[datetime] = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.debug("BeautifulSoup not installed; calendar parse skipped")
        return events
    try:
        soup = BeautifulSoup(html, "html.parser")
        # Find impact indicators (High = red/high)
        # Common patterns: class containing 'high', or title/text "High"
        for elem in soup.find_all(string=re.compile(r"\bhigh\b", re.I)):
            parent = elem.parent
            if not parent:
                continue
            # Walk up to find a row or container with time
            row = parent
            for _ in range(10):
                if row is None:
                    break
                if getattr(row, "name", None) in ("tr", "li", "div"):
                    text = row.get_text(separator=" ", strip=True)
                    # Time pattern: 8:30am, 8:30 am, 08:30
                    time_m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)?", text, re.I)
                    if time_m:
                        h, m = int(time_m.group(1)), int(time_m.group(2))
                        if time_m.group(3) and "pm" in (time_m.group(3) or "").lower():
                            if h < 12:
                                h += 12
                        elif time_m.group(3) and "am" in (time_m.group(3) or "").lower() and h == 12:
                            h = 0
                        try:
                            event_dt = today_est.replace(hour=h, minute=m, second=0, microsecond=0)
                            events.append(event_dt)
                        except ValueError:
                            pass
                    break
                row = getattr(row, "parent", None)

        # Deduplicate by time
        seen = set()
        unique = []
        for dt in events:
            key = (dt.hour, dt.minute)
            if key not in seen:
                seen.add(key)
                unique.append(dt)
        return unique
    except Exception as e:
        logger.warning("Economic calendar parse error: %s", e)
    return events


def _manual_times_today_est() -> list[datetime]:
    """Convert CALENDAR_MANUAL_HIGH_IMPACT_TIMES (e.g. ['8:30', '10:00']) to today EST."""
    out = []
    now = datetime.now(EST)
    for s in CALENDAR_MANUAL_HIGH_IMPACT_TIMES:
        s = s.strip()
        if not s:
            continue
        m = re.match(r"(\d{1,2}):(\d{2})", s)
        if m:
            try:
                h, m = int(m.group(1)), int(m.group(2))
                out.append(now.replace(hour=h, minute=m, second=0, microsecond=0))
            except ValueError:
                pass
    return out


def fetch_high_impact_times_est() -> list[datetime]:
    """Fetch times (EST) of high-impact economic events for today. Cached for CALENDAR_CACHE_MINUTES."""
    global _CALENDAR_CACHE, _CALENDAR_CACHE_TIME
    if not USE_ECONOMIC_CALENDAR:
        return []
    now_ts = time.time()
    if _CALENDAR_CACHE and (now_ts - _CALENDAR_CACHE_TIME) < (CALENDAR_CACHE_MINUTES * 60):
        return _CALENDAR_CACHE

    # Manual times from config (no cache bypass)
    manual = _manual_times_today_est()
    if manual:
        _CALENDAR_CACHE = manual
        _CALENDAR_CACHE_TIME = now_ts
        return manual

    try:
        from config import ECONOMIC_CALENDAR_URL
        url = ECONOMIC_CALENDAR_URL or "https://www.forexfactory.com/calendar"
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MNQBot/1.0)"},
            timeout=10,
        )
        if resp.ok:
            today_est = datetime.now(EST)
            events = _parse_forexfactory(resp.text, today_est)
            if events:
                _CALENDAR_CACHE[:] = events
                _CALENDAR_CACHE_TIME = now_ts
                return events
    except Exception as e:
        logger.warning("Economic calendar fetch failed: %s", e)
    return _CALENDAR_CACHE if _CALENDAR_CACHE else []


def is_near_news(now_est: datetime, buffer_minutes: int | None = None) -> bool:
    """
    Return True if now_est is within buffer_minutes of any high-impact event.
    If no calendar data, returns False (allow trading).
    """
    buffer = buffer_minutes if buffer_minutes is not None else NEWS_BUFFER_MINUTES
    events = fetch_high_impact_times_est()
    window = timedelta(minutes=buffer)
    for event_time in events:
        if abs((now_est - event_time).total_seconds()) <= window.total_seconds():
            return True
    return False
