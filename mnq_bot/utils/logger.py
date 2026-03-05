"""
Trade journal (CSV) and application logging.
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from pathlib import Path

from config import JOURNAL_PATH, LOG_DIR, LOG_LEVEL, LOG_TRADES

LOG_DIR.mkdir(parents=True, exist_ok=True)
JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)

JOURNAL_HEADER = [
    "timestamp", "direction", "entry", "stop", "tp1", "tp2",
    "result", "exit_price", "rr", "notes",
]


def setup_logging() -> None:
    """Configure root logger and file handler."""
    log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if not LOG_DIR.exists():
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_DIR / "mnq_bot.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)

    # Suppress noisy loggers that flood with every HTTP poll
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("hpack").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING)
    logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)


def log_trade(
    direction: str,
    entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    result: str,  # "win" | "loss" | "breakeven" | "partial"
    exit_price: float | None = None,
    rr: float | None = None,
    notes: str = "",
) -> None:
    """Append one row to trade journal CSV."""
    if not LOG_TRADES:
        return
    file_exists = JOURNAL_PATH.exists()
    with open(JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(JOURNAL_HEADER)
        w.writerow([
            datetime.utcnow().isoformat(),
            direction,
            entry,
            stop,
            tp1,
            tp2,
            result,
            exit_price or "",
            rr or "",
            notes,
        ])
