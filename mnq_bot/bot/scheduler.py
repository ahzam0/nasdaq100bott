"""
Session timing: when to start/stop scanning, when to send daily summary.
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import (
    DAILY_SUMMARY_HOUR,
    PREMARKET_START,
    RTH_END,
)

logger = logging.getLogger(__name__)

EST = ZoneInfo("America/New_York")


def now_est() -> datetime:
    return datetime.now(EST)


def in_scan_window() -> bool:
    """True if current time (EST) is within scan window (default 7:00–11:00 AM EST)."""
    t = now_est().time()
    start = time(int(PREMARKET_START.split(":")[0]), int(PREMARKET_START.split(":")[1]))
    end = time(int(RTH_END.split(":")[0]), int(RTH_END.split(":")[1]))
    return start <= t < end


def create_scheduler() -> AsyncIOScheduler:
    """APScheduler instance for cron jobs."""
    return AsyncIOScheduler(timezone=EST)


def schedule_daily_summary(scheduler: AsyncIOScheduler, job_func) -> None:
    """Run job_func at 11:00 AM EST daily."""
    scheduler.add_job(
        job_func,
        CronTrigger(hour=DAILY_SUMMARY_HOUR, minute=0, timezone=EST),
        id="daily_summary",
    )


def schedule_scan_loop(scheduler: AsyncIOScheduler, job_func, interval_seconds: int = 60) -> None:
    """Run job_func every interval_seconds (e.g. every 1 min for 1m candle close)."""
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler.add_job(
        job_func,
        IntervalTrigger(seconds=interval_seconds),
        id="scan_loop",
    )
