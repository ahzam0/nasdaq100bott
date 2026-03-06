"""
Daily signal format — exact output required for NAS100.
"""

from __future__ import annotations

from datetime import datetime
from typing import List


def format_nas100_signal(
    date_str: str,
    session: str,
    direction: str,
    entry_zone_lo: float,
    entry_zone_hi: float,
    sl: float,
    sl_points: float,
    tp1: float,
    tp2: float,
    tp3_note: str,
    risk_pct: float,
    setup_type: str,
    confluence_score: int,
    confluences_passed: List[str],
    confluences_failed: List[str],
    confidence: float,
    invalidation: str,
    news_ok: bool = True,
) -> str:
    return f"""
DATE: {date_str}
ASSET: NAS100 (NASDAQ 100 CFD)
SESSION: {session}
------------------------------------------------------------

SIGNAL #1
DIRECTION: {direction}
ENTRY ZONE: {entry_zone_lo:,.0f} - {entry_zone_hi:,.0f}
STOP LOSS: {sl:,.0f} ({sl_points:.0f} points below entry)
TAKE PROFIT 1: {tp1:,.0f} (1:2 RR - close 50%)
TAKE PROFIT 2: {tp2:,.0f} (1:3.5 RR - close 40%)
TAKE PROFIT 3: {tp3_note}
RISK: {risk_pct}% of account
SETUP TYPE: {setup_type}
ENTRY TIMEFRAME: M15
BIAS TIMEFRAME: H1 + H4 + D1

CONFLUENCE SCORE: {confluence_score}/7
  """ + "\n  ".join("OK " + c for c in confluences_passed) + "\n  " + "\n  ".join("X " + c for c in confluences_failed) + f"""

CONFIDENCE: {confidence}/10
INVALIDATION: {invalidation}
NEWS CHECK: {"No major news next 2 hours OK" if news_ok else "CHECK CALENDAR"}
------------------------------------------------------------"""


def daily_header(date_str: str, session: str) -> str:
    return f"""
============================================================
DATE: {date_str}
ASSET: NAS100 (NASDAQ 100 CFD)
SESSION: {session}
============================================================"""
