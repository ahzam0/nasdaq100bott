"""Load and expose config.yaml and env. Zero magic numbers."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# Load .env if present
_env_path = ROOT / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
    except ImportError:
        pass

_config_path = ROOT / "config.yaml"
_raw: dict = {}
if _config_path.exists():
    with open(_config_path, "r", encoding="utf-8") as f:
        _raw = yaml.safe_load(f) or {}

def get(key_path: str, default=None):
    """Get nested key, e.g. 'targets.sharpe_ratio'."""
    keys = key_path.split(".")
    v = _raw
    for k in keys:
        v = (v or {}).get(k)
        if v is None:
            return default
    return v

# Convenience
PROJECT_NAME = get("project.name", "nasdaq-quantum-trading-bot")
TIMEZONE = get("project.timezone", "America/New_York")
TARGETS = _raw.get("targets", {})
MARKET_HOURS = _raw.get("market_hours", {})
OPTIMIZATION = _raw.get("optimization", {})
BACKTEST = _raw.get("backtest", {})
DATA = _raw.get("data", {})
QUANTUM = _raw.get("quantum", {})
STRATEGIES = _raw.get("strategies", {})
RISK = _raw.get("risk", {})
UNIVERSE = _raw.get("universe", {})
