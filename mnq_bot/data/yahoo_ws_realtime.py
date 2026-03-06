"""
Free minimal-delay price via Yahoo Finance WebSocket (no API key).
Streams QQQ and scales to NQ equivalent. Run in background thread.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

YAHOO_WS_SYMBOL = "QQQ"
# NQ = QQQ * ratio. Calibrate to match broker (e.g. NQ 24,565 with QQQ ~597 → ratio ≈ 41)
DEFAULT_QQQ_TO_NQ_RATIO = 41.15


# Keys yfinance WebSocket may use (protobuf-derived or API-dependent)
_PRICE_KEYS = (
    "regularMarketPrice", "regularMarketPreviousClose", "regularMarketLastPrice",
    "price", "lastPrice", "close", "marketPrice", "previousClose",
)

def _extract_price(msg: Any) -> Optional[float]:
    """Extract price from Yahoo WS message (dict or nested)."""
    if not isinstance(msg, dict):
        return None
    for key in _PRICE_KEYS:
        v = msg.get(key)
        if v is not None:
            try:
                p = float(v)
                if p > 0 and p < 1e7:
                    return p
            except (TypeError, ValueError):
                pass
    # Nested dicts (e.g. quote, price object)
    for v in msg.values():
        if isinstance(v, dict):
            p = _extract_price(v)
            if p is not None:
                return p
    return None


class YahooWSClient:
    """
    Yahoo Finance WebSocket client. Subscribes to QQQ, keeps last price, exposes NQ equivalent.
    """

    def __init__(self, symbol: str = YAHOO_WS_SYMBOL, qqq_to_nq_ratio: float = DEFAULT_QQQ_TO_NQ_RATIO):
        self._symbol = symbol
        self._ratio = qqq_to_nq_ratio
        self._last_quote_price: Optional[float] = None
        self._connected = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._ws = None

    def get_last_price(self) -> Optional[float]:
        return self._last_quote_price

    def get_nq_equivalent_price(self) -> Optional[float]:
        if self._last_quote_price is not None and self._ratio:
            return self._last_quote_price * self._ratio
        return None

    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_ws, daemon=True)
        self._thread.start()
        for _ in range(40):
            if self._last_quote_price is not None:
                break
            time.sleep(0.25)

    def stop(self) -> None:
        self._stop.set()
        self._connected = False

    def _run_ws(self) -> None:
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed. pip install yfinance")
            return
        reconnect_delay = 2.0
        max_reconnects_after_thread_error = 3
        thread_error_count = 0
        while not self._stop.is_set():
            try:
                with yf.WebSocket(verbose=False) as ws:
                    self._ws = ws
                    ws.subscribe([self._symbol])
                    thread_error_count = 0
                    reconnect_delay = 2.0

                    def on_msg(msg):
                        if self._stop.is_set():
                            return
                        self._connected = True
                        p = _extract_price(msg)
                        if p is not None:
                            self._last_quote_price = p

                    ws.listen(on_msg)
            except RuntimeError as e:
                if "can't start new thread" in str(e).lower() or "thread" in str(e).lower():
                    thread_error_count += 1
                    logger.warning(
                        "Yahoo WS: thread limit reached (can't start new thread). "
                        "Set MNQ_YAHOO_WS_REALTIME=false to use REST-only. Attempt %d/%d.",
                        thread_error_count,
                        max_reconnects_after_thread_error,
                    )
                    if thread_error_count >= max_reconnects_after_thread_error:
                        logger.error(
                            "Yahoo WebSocket disabled after %d thread errors. "
                            "Use MNQ_YAHOO_WS_REALTIME=false or increase process thread limit.",
                            max_reconnects_after_thread_error,
                        )
                        return
                    reconnect_delay = min(60.0, reconnect_delay * 5)
                else:
                    raise
            except Exception as e:
                logger.debug("Yahoo WS error: %s", e)
            self._ws = None
            if self._stop.is_set():
                break
            time.sleep(reconnect_delay)


# Singleton so we never create multiple Yahoo WS clients (avoids thread exhaustion).
_yahoo_ws_singleton: Optional[YahooWSClient] = None
_yahoo_ws_singleton_lock = threading.Lock()


def get_or_create_yahoo_ws_client(
    symbol: str = YAHOO_WS_SYMBOL,
    qqq_to_nq_ratio: float = DEFAULT_QQQ_TO_NQ_RATIO,
    auto_start: bool = True,
) -> Optional[YahooWSClient]:
    """Return the single shared Yahoo WebSocket client. When auto_start=True (default), starts immediately; when False, call start() when session begins."""
    global _yahoo_ws_singleton
    with _yahoo_ws_singleton_lock:
        if _yahoo_ws_singleton is not None:
            return _yahoo_ws_singleton
        client = YahooWSClient(symbol=symbol, qqq_to_nq_ratio=qqq_to_nq_ratio)
        if auto_start:
            client.start()
        _yahoo_ws_singleton = client
    return client


def create_yahoo_ws_client(
    symbol: str = YAHOO_WS_SYMBOL,
    qqq_to_nq_ratio: float = DEFAULT_QQQ_TO_NQ_RATIO,
) -> Optional[YahooWSClient]:
    """Create and start Yahoo WebSocket client (singleton). Free, no API key."""
    return get_or_create_yahoo_ws_client(symbol=symbol, qqq_to_nq_ratio=qqq_to_nq_ratio)
