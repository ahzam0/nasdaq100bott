"""
NASDAQ 100 (NAS100/US100) Elite Signal System — CFD with leverage.
Targets: >=1 signal/day | >=70% win rate | >=40% monthly return | PF >=2.0 | DD <=15%
"""

from nas100_elite.config import (
    TARGETS,
    POINT_VALUE_PER_LOT,
    LEVERAGE,
    CIRCUIT_BREAKERS,
    SESSION_WINDOWS,
    SL_POINTS_MIN,
    SL_POINTS_MAX,
    ASSET_NAME,
    ASSET_DISPLAY,
)

__all__ = [
    "TARGETS",
    "POINT_VALUE_PER_LOT",
    "LEVERAGE",
    "CIRCUIT_BREAKERS",
    "SESSION_WINDOWS",
    "SL_POINTS_MIN",
    "SL_POINTS_MAX",
]
