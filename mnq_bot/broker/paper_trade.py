"""
Paper trading: simulates fills and positions in memory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from broker.base import Broker, OrderResult

logger = logging.getLogger(__name__)


@dataclass
class PaperPosition:
    symbol: str
    side: str
    contracts: int
    entry_price: float
    stop_order_id: str | None = None
    stop_price: float = 0.0


class PaperBroker(Broker):
    def __init__(self):
        self._positions: dict[str, PaperPosition] = {}
        self._order_id = 0
        self._connected = True

    def _next_id(self) -> str:
        self._order_id += 1
        return f"paper_{self._order_id}"

    def place_market_order(self, symbol: str, side: str, contracts: int) -> OrderResult:
        if not self._connected:
            return OrderResult(False, message="Not connected")
        # Paper: assume fill at "current" price; we don't have live price here, so caller passes via context or we use 0
        # In real flow, main loop passes last known price.
        key = symbol
        if key in self._positions:
            pos = self._positions[key]
            if (pos.side == "BUY" and side == "SELL") or (pos.side == "SELL" and side == "BUY"):
                # Closing
                self._positions.pop(key, None)
                return OrderResult(True, self._next_id(), None, "Paper close")
            # Adding to position
            pos.contracts += contracts if side == "BUY" else -contracts
            if pos.contracts == 0:
                self._positions.pop(key, None)
            return OrderResult(True, self._next_id(), None, "Paper add")
        entry = 0.0  # Caller should set via set_last_price for paper
        self._positions[key] = PaperPosition(
            symbol=symbol,
            side=side,
            contracts=contracts,
            entry_price=entry,
        )
        return OrderResult(True, self._next_id(), entry, "Paper open")

    def place_stop_order(self, symbol: str, side: str, contracts: int, stop_price: float) -> OrderResult:
        key = symbol
        if key not in self._positions:
            return OrderResult(False, message="No position to attach stop")
        pos = self._positions[key]
        oid = self._next_id()
        pos.stop_order_id = oid
        pos.stop_price = stop_price
        return OrderResult(True, oid, None, "Paper stop placed")

    def update_stop(self, order_id: str, new_stop: float) -> bool:
        for pos in self._positions.values():
            if pos.stop_order_id == order_id:
                pos.stop_price = new_stop
                return True
        return False

    def get_position(self, symbol: str) -> int:
        if symbol not in self._positions:
            return 0
        pos = self._positions[symbol]
        return pos.contracts if pos.side == "BUY" else -pos.contracts

    def is_connected(self) -> bool:
        return self._connected

    def set_fill_price(self, symbol: str, price: float) -> None:
        """For paper: set entry price when we don't have real fill."""
        if symbol in self._positions:
            self._positions[symbol].entry_price = price
