"""
Live order flow state: delta, buy/sell volume, imbalance.
Fed by: Order Flow API (POST /orderflow/push), Tradovate trade stream, or simulated from price.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")


@dataclass
class OrderFlowSummary:
    """Snapshot of order flow for strategy use."""
    session_delta: int          # Cumulative session delta (buy_vol - sell_vol)
    buy_volume: int
    sell_volume: int
    cumulative_delta: int
    imbalance_ratio: float      # (buy - sell) / (buy + sell), -1 to 1
    last_price: float | None
    last_updated_ts: float
    source: str                 # "live" | "simulated" | "push"
    trade_count: int = 0


class OrderFlowStore:
    """
    In-memory order flow state. Thread-safe.
    Push trades via push_trade(); read summary via get_summary().
    """

    def __init__(self, session_reset_hour_est: int = 7):
        self._lock = threading.Lock()
        self._buy_volume = 0
        self._sell_volume = 0
        self._cumulative_delta = 0
        self._session_delta = 0
        self._last_price: float | None = None
        self._last_updated = time.time()  # So age_seconds is 0 until first update
        self._source = "push"
        self._trade_count = 0
        self._session_reset_hour = session_reset_hour_est
        self._last_session_date: str | None = None

    def _maybe_reset_session(self) -> None:
        """Reset session delta at start of new session (e.g. 7 AM EST)."""
        now = datetime.now(EST)
        today = now.strftime("%Y-%m-%d")
        if self._last_session_date != today and now.hour >= self._session_reset_hour:
            self._session_delta = 0
            self._last_session_date = today

    def push_trade(self, price: float, size: int, side: str) -> None:
        """Record one trade. side = 'buy' | 'sell'."""
        with self._lock:
            self._maybe_reset_session()
            self._trade_count += 1
            self._last_price = price
            if side.lower() in ("buy", "b", "bid"):
                self._buy_volume += size
                self._session_delta += size
                self._cumulative_delta += size
            else:
                self._sell_volume += size
                self._session_delta -= size
                self._cumulative_delta -= size
            self._last_updated = time.time()
            self._source = "live"

    def set_delta_proxy(self, session_delta: int, buy_vol: int, sell_vol: int, last_price: float | None, source: str = "simulated") -> None:
        """Set state from external source (e.g. simulated from candle)."""
        with self._lock:
            self._maybe_reset_session()
            self._session_delta = session_delta
            self._buy_volume = buy_vol
            self._sell_volume = sell_vol
            self._cumulative_delta = session_delta
            self._last_price = last_price
            self._last_updated = time.time()
            self._source = source

    def get_summary(self) -> OrderFlowSummary:
        with self._lock:
            total = self._buy_volume + self._sell_volume
            if total > 0:
                imb = (self._buy_volume - self._sell_volume) / total
            else:
                imb = 0.0
            return OrderFlowSummary(
                session_delta=self._session_delta,
                buy_volume=self._buy_volume,
                sell_volume=self._sell_volume,
                cumulative_delta=self._cumulative_delta,
                imbalance_ratio=round(imb, 4),
                last_price=self._last_price,
                last_updated_ts=self._last_updated,
                source=self._source,
                trade_count=self._trade_count,
            )

    def is_stale(self, max_age_seconds: float = 60.0) -> bool:
        """True if no update in max_age_seconds."""
        return (time.time() - self._last_updated) > max_age_seconds


# Global store for the API server and strategy
_store: OrderFlowStore | None = None
_store_lock = threading.Lock()


def get_orderflow_store() -> OrderFlowStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = OrderFlowStore(session_reset_hour_est=7)
        return _store
