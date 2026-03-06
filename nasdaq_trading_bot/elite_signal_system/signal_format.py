"""
Mandatory signal format: every signal must include asset, direction, entry, SL, TP, risk %, confluences, confidence, invalidation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class Signal:
    asset: str
    direction: str  # "BUY" | "SELL"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    entry_range_high: float | None = None  # optional range
    take_profit_2: float | None = None
    risk_pct: float = 1.5
    timeframe: str = "H1"
    confluences: List[str] = field(default_factory=list)
    confidence: float = 8.0  # out of 10
    invalidation: str = ""
    rr_ratio: float = 2.0
    session: str = ""

    def __post_init__(self):
        if self.entry_range_high is None:
            self.entry_range_high = self.entry_price
        if len(self.confluences) < 3:
            self.confluences.extend([""] * (3 - len(self.confluences)))
        if self.risk_pct > 2.0:
            self.risk_pct = 2.0

    def to_daily_format(self, date_str: str, signal_number: int) -> str:
        entry_str = f"{self.entry_price:.2f}" if self.entry_price == self.entry_range_high else f"{self.entry_price:.2f} – {self.entry_range_high:.2f}"
        tp2_str = f"\n✅ TAKE PROFIT 2: {self.take_profit_2:.2f} (1:3 RR)" if self.take_profit_2 else ""
        conf_str = "\n   ".join(f"→ {c}" for c in self.confluences if c)
        return f"""
SIGNAL #{signal_number}
🔵 PAIR: {self.asset}
📈 DIRECTION: {self.direction}
🎯 ENTRY: {entry_str}
🛑 STOP LOSS: {self.stop_loss:.2f}
✅ TAKE PROFIT 1: {self.take_profit_1:.2f} (1:2 RR){tp2_str}
💼 RISK: {self.risk_pct}% of account
⏱ TIMEFRAME: {self.timeframe}
📌 CONFLUENCES:
   {conf_str}
🔢 CONFIDENCE: {self.confidence}/10
❌ INVALIDATION: {self.invalidation}
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
