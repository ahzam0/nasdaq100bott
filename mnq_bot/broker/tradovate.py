"""
Tradovate REST API integration (stub). Replace with real API calls.
"""

from __future__ import annotations

import logging
from typing import Optional

import requests

from broker.base import Broker, OrderResult
from config import TRADOVATE_ACCESS_TOKEN, TRADOVATE_API_URL, TRADOVATE_DEV_KEY

logger = logging.getLogger(__name__)


class TradovateBroker(Broker):
    def __init__(self):
        self._token = TRADOVATE_ACCESS_TOKEN
        self._base = TRADOVATE_API_URL
        self._connected = bool(self._token)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def place_market_order(self, symbol: str, side: str, contracts: int) -> OrderResult:
        if not self._connected:
            return OrderResult(False, message="Tradovate not connected")
        # Stub: real implementation would POST /order/placeOrder or similar
        logger.warning("Tradovate place_market_order stub – not implemented")
        return OrderResult(False, message="Tradovate API not implemented")

    def place_stop_order(self, symbol: str, side: str, contracts: int, stop_price: float) -> OrderResult:
        if not self._connected:
            return OrderResult(False, message="Tradovate not connected")
        logger.warning("Tradovate place_stop_order stub – not implemented")
        return OrderResult(False, message="Tradovate API not implemented")

    def update_stop(self, order_id: str, new_stop: float) -> bool:
        logger.warning("Tradovate update_stop stub – not implemented")
        return False

    def get_position(self, symbol: str) -> int:
        if not self._connected:
            return 0
        # Stub: GET positions endpoint
        return 0

    def is_connected(self) -> bool:
        return self._connected
