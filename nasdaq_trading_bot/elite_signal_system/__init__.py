"""
Elite Trading Signal System — Hit-and-trial until all 5 metrics are met:
  Signals/day >= 1, Win rate >= 70%, Monthly return >= 40%, Profit factor >= 2.0, Max DD < 15%
"""

from elite_signal_system.config import TARGETS
from elite_signal_system.signal_format import Signal

__all__ = ["TARGETS", "Signal"]
