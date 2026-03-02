"""
Base broker interface: place order, update stop, get position.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    message: str = ""


class Broker(ABC):
    @abstractmethod
    def place_market_order(
        self,
        symbol: str,
        side: str,  # "BUY" | "SELL"
        contracts: int,
    ) -> OrderResult:
        pass

    @abstractmethod
    def place_stop_order(
        self,
        symbol: str,
        side: str,
        contracts: int,
        stop_price: float,
    ) -> OrderResult:
        pass

    @abstractmethod
    def update_stop(self, order_id: str, new_stop: float) -> bool:
        """Move stop to new_stop. Returns True if accepted."""
        pass

    @abstractmethod
    def get_position(self, symbol: str) -> int:
        """Current position in contracts (+ long, - short, 0 flat)."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        pass
