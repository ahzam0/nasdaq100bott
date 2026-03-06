"""Structured JSON logging for iteration, timestamp, regime, metrics snapshot."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
) -> None:
    """Configure root logger and optional file handler."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    logging.basicConfig(level=getattr(logging, level.upper()), format=fmt)
    if log_file:
        fpath = LOG_DIR / log_file
        fh = logging.FileHandler(fpath, encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt))
        logging.getLogger().addHandler(fh)


def log_iteration(
    run_number: int,
    iteration: int,
    metrics: Any,
    score: float,
    targets_hit: int,
) -> None:
    """Write one structured log line (JSON) for iteration."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "run": run_number,
        "iteration": iteration,
        "score": score,
        "targets_hit": targets_hit,
    }
    if metrics is not None and hasattr(metrics, "__dict__"):
        m = metrics
        out["metrics"] = {
            "sharpe_ratio": getattr(m, "sharpe_ratio", None),
            "cagr_pct": getattr(m, "cagr_pct", None),
            "max_drawdown_pct": getattr(m, "max_drawdown_pct", None),
            "win_rate_pct": getattr(m, "win_rate_pct", None),
        }
    path = LOG_DIR / "optimization.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(out) + "\n")
