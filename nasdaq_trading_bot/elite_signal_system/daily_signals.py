"""
Produce daily signals in the exact required format.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from elite_signal_system.signal_format import Signal


def format_daily_header(date: str, session: str = "New York") -> str:
    return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATE: {date}
SESSION: {session}
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


def format_signal(s: Signal, signal_number: int, date_str: str = "") -> str:
    entry_str = f"{s.entry_price:.2f}" if s.entry_range_high is None or s.entry_price == s.entry_range_high else f"{s.entry_price:.2f} - {s.entry_range_high:.2f}"
    tp2 = f"\nTAKE PROFIT 2: {s.take_profit_2:.2f} (1:3 RR)" if s.take_profit_2 else ""
    confluences = "\n   ".join(f"-> {c}" for c in (s.confluences or []) if c)
    return f"""
SIGNAL #{signal_number}
PAIR: {s.asset}
DIRECTION: {s.direction}
ENTRY: {entry_str}
STOP LOSS: {s.stop_loss:.2f}
TAKE PROFIT 1: {s.take_profit_1:.2f} (1:2 RR){tp2}
RISK: {s.risk_pct}% of account
TIMEFRAME: {s.timeframe}
CONFLUENCES:
   {confluences}
CONFIDENCE: {s.confidence}/10
INVALIDATION: {s.invalidation}
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


def produce_daily_report(signals: List[Signal], date: datetime | None = None, session: str = "New York") -> str:
    date = date or datetime.now()
    date_str = date.strftime("%d/%m/%Y")
    out = format_daily_header(date_str, session)
    for i, s in enumerate(signals, 1):
        out += format_signal(s, i, date_str)
    return out
