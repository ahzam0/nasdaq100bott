"""
NAS100 Signal System v3.0 — Rebuilt from scratch.
Priority: signals/day >= 1 first, then optimize win rate to 70%.
Simple mechanical rules only; no 5/7 confluence gate.
"""

from nas100_v3.config import TARGETS, RISK_TABLE, CIRCUIT_BREAKERS_V3

__all__ = ["TARGETS", "RISK_TABLE", "CIRCUIT_BREAKERS_V3"]
