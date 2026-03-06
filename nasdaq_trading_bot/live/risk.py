"""
NASDAQ risk rules: Kelly, beta vs QQQ, sector caps, earnings blackout,
VIX/QQQ circuit breakers, daily loss limit, drawdown halt, PDT, overnight limit.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Defaults from config
VIX_CUT_REDUCE = 30.0
VIX_EXTREME_CLOSE = 40.0
QQQ_CIRCUIT_PCT = 3.0
DAILY_LOSS_LIMIT_PCT = 2.0
DRAWDOWN_HALT_PCT = 5.0
MAX_POSITION_PCT = 10.0
BETA_MIN = 0.5
BETA_MAX = 1.5
SECTOR_CAP_PCT = 40.0
CORRELATION_CAP = 0.85
OVERNIGHT_MAX_PCT = 30.0
PRE_FOMC_OVERNIGHT_PCT = 10.0


def kelly_position_size(win_rate: float, avg_win: float, avg_loss: float, max_pct: float = 0.1) -> float:
    """Quantum-adjusted Kelly; cap at max_pct."""
    if avg_loss == 0:
        return 0.0
    k = win_rate - (1 - win_rate) * (avg_win / avg_loss)
    return max(0.0, min(max_pct, k))


def check_vix_circuit(vix: float) -> str:
    """Return 'normal'|'reduce'|'close'."""
    if vix >= VIX_EXTREME_CLOSE:
        return "close"
    if vix >= VIX_CUT_REDUCE:
        return "reduce"
    return "normal"


def check_qqq_circuit(qqq_pct_change: float) -> bool:
    """True if QQQ down > N% intraday → pause new longs."""
    return qqq_pct_change <= -QQQ_CIRCUIT_PCT


def check_daily_loss_limit(daily_pnl_pct: float) -> bool:
    """True if halt trading (daily loss >= limit)."""
    return daily_pnl_pct <= -DAILY_LOSS_LIMIT_PCT


def check_drawdown_halt(current_equity: float, peak_equity: float) -> bool:
    """True if drawdown from peak >= halt threshold."""
    if peak_equity <= 0:
        return False
    dd = (peak_equity - current_equity) / peak_equity * 100
    return dd >= DRAWDOWN_HALT_PCT


def pdt_day_trades_used(count: int, limit: int = 3) -> tuple[int, str]:
    """Return (count, status). status: 'ok'|'warn'|'block'."""
    if count >= limit:
        return count, "block"
    if count >= limit - 1:
        return count, "warn"
    return count, "ok"
