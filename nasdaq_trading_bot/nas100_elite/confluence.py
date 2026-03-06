"""
Confluence scoring: 7 items, need >= 5 to enter. Score 7 → 2% risk, 6 → 1.5%, 5 → 1%.
"""

from __future__ import annotations

from typing import List, Tuple

from nas100_elite.config import CONFLUENCE_MIN_TO_ENTER, RISK_PCT_BY_SCORE


CONFLUENCE_LABELS = [
    "D1 trend direction confirmed (price vs 200 EMA)",
    "H4 structure aligned (HH/HL for buys, LH/LL for sells)",
    "Price at key zone (OB, PDH/PDL, round number, ORB level)",
    "Valid M15 entry trigger (engulfing, pin bar, BOS)",
    "RSI not opposing on H1 (not >75 buys, not <25 sells)",
    "Volume confirms (above 20-period average)",
    "Risk-to-Reward >= 1:2",
]


def score_confluence(
    d1_trend_ok: bool,
    h4_structure_ok: bool,
    at_key_zone: bool,
    m15_trigger_ok: bool,
    rsi_ok: bool,
    volume_ok: bool,
    rr_ok: bool,
) -> Tuple[int, float, List[str], List[str]]:
    """
    Returns (score 0-7, risk_pct, list of checks passed, list of checks failed).
    """
    checks = [
        ("D1 trend", d1_trend_ok),
        ("H4 structure", h4_structure_ok),
        ("Key zone", at_key_zone),
        ("M15 trigger", m15_trigger_ok),
        ("RSI", rsi_ok),
        ("Volume", volume_ok),
        ("RR >= 1:2", rr_ok),
    ]
    passed = [CONFLUENCE_LABELS[i] for i, (_, ok) in enumerate(checks) if ok]
    failed = [CONFLUENCE_LABELS[i] for i, (_, ok) in enumerate(checks) if not ok]
    score = sum(1 for _, ok in checks if ok)
    risk_pct = RISK_PCT_BY_SCORE.get(score, 0.0)
    return score, risk_pct, passed, failed


def may_enter(score: int) -> bool:
    return score >= CONFLUENCE_MIN_TO_ENTER
