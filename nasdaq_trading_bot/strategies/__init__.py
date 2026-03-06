"""
NASDAQ (NAS100/NDX) strategy library — top proven approaches.
1. Trend Following (swing/position)
2. Smart Money Concepts (day)
3. Breakout (momentum)
4. Multi-Timeframe Intraday (all-around)
5. Momentum/Risk-Adjusted (investors)
+ Risk rules and best times.
"""

from strategies.base import BaseStrategy
from strategies.trend_following_nasdaq import TrendFollowingNasdaqStrategy
from strategies.smart_money_nasdaq import SmartMoneyNasdaqStrategy
from strategies.breakout_nasdaq import BreakoutNasdaqStrategy
from strategies.multi_timeframe_nasdaq import MultiTimeframeNasdaqStrategy
from strategies.momentum_risk_adjusted_nasdaq import MomentumRiskAdjustedNasdaqStrategy

__all__ = [
    "BaseStrategy",
    "TrendFollowingNasdaqStrategy",
    "SmartMoneyNasdaqStrategy",
    "BreakoutNasdaqStrategy",
    "MultiTimeframeNasdaqStrategy",
    "MomentumRiskAdjustedNasdaqStrategy",
]
