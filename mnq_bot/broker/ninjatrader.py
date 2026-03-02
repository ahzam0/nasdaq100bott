"""
NinjaTrader ATI (Automated Trading Interface) connection (stub).
Uses ATI DLL or socket to send orders. Replace with real ATI client.
"""

from __future__ import annotations

import logging
from typing import Optional

from broker.base import Broker, OrderResult
from config import NINJATRADER_ATI_HOST, NINJATRADER_ATI_PORT

logger = logging.getLogger(__name__)


class NinjaTraderBroker(Broker):
    def __init__(self):
        self._host = NINJATRADER_ATI_HOST
        self._port = NINJATRADER_ATI_PORT
        self._connected = False
        # Real impl: connect via socket or ATI DLL

    def place_market_order(self, symbol: str, side: str, contracts: int) -> OrderResult:
        if not self._connected:
            return OrderResult(False, message="NinjaTrader ATI not connected")
        logger.warning("NinjaTrader place_market_order stub – not implemented")
        return OrderResult(False, message="NinjaTrader ATI not implemented")

    def place_stop_order(self, symbol: str, side: str, contracts: int, stop_price: float) -> OrderResult:
        if not self._connected:
            return OrderResult(False, message="NinjaTrader ATI not connected")
        logger.warning("NinjaTrader place_stop_order stub – not implemented")
        return OrderResult(False, message="NinjaTrader ATI not implemented")

    def update_stop(self, order_id: str, new_stop: float) -> bool:
        logger.warning("NinjaTrader update_stop stub – not implemented")
        return False

    def get_position(self, symbol: str) -> int:
        if not self._connected:
            return 0
        return 0

    def is_connected(self) -> bool:
        return self._connected
