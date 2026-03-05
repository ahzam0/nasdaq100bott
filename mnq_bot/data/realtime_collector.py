"""
Real-time trade & quote collector via free WebSocket feeds.

Sources (tried in order):
  1. Alpaca IEX  – real-time QQQ trades + quotes (free tier, needs API key)
  2. Finnhub     – real-time QQQ trades (free tier, needs API key)

Classified trades are pushed into the global OrderFlowStore and an
internal rolling buffer used by the order-flow engine.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

NQ_QQQ_RATIO = 41.15  # NQ ≈ QQQ × this


@dataclass
class ClassifiedTrade:
    """A single trade classified as buy or sell."""
    timestamp: float          # UNIX epoch seconds
    price_qqq: float          # raw QQQ price
    price_nq: float           # scaled to NQ equivalent
    size: int                 # share count
    side: str                 # "buy" | "sell"
    classification: str       # "quote" (bid/ask) | "tick" (tick rule) | "unknown"


@dataclass
class QuoteSnapshot:
    """Latest bid/ask for trade classification."""
    bid: float = 0.0
    ask: float = 0.0
    bid_size: int = 0
    ask_size: int = 0
    timestamp: float = 0.0


class TradeBuffer:
    """Thread-safe rolling buffer of classified trades."""

    def __init__(self, maxlen: int = 50_000):
        self._trades: deque[ClassifiedTrade] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._total_buy_vol: int = 0
        self._total_sell_vol: int = 0
        self._trade_count: int = 0
        self._last_price: float = 0.0
        self._session_start: float = time.time()

    def push(self, trade: ClassifiedTrade) -> None:
        with self._lock:
            self._trades.append(trade)
            self._trade_count += 1
            self._last_price = trade.price_nq
            if trade.side == "buy":
                self._total_buy_vol += trade.size
            else:
                self._total_sell_vol += trade.size

    def get_trades(self, last_n: int | None = None) -> list[ClassifiedTrade]:
        with self._lock:
            if last_n is None:
                return list(self._trades)
            return list(self._trades)[-last_n:]

    def get_trades_since(self, since_epoch: float) -> list[ClassifiedTrade]:
        with self._lock:
            return [t for t in self._trades if t.timestamp >= since_epoch]

    @property
    def trade_count(self) -> int:
        with self._lock:
            return self._trade_count

    @property
    def last_price(self) -> float:
        with self._lock:
            return self._last_price

    @property
    def total_buy_vol(self) -> int:
        with self._lock:
            return self._total_buy_vol

    @property
    def total_sell_vol(self) -> int:
        with self._lock:
            return self._total_sell_vol

    def reset_session(self) -> None:
        with self._lock:
            self._trades.clear()
            self._total_buy_vol = 0
            self._total_sell_vol = 0
            self._trade_count = 0
            self._session_start = time.time()


# ---------------------------------------------------------------------------
# Alpaca IEX WebSocket collector
# ---------------------------------------------------------------------------
class AlpacaCollector:
    """
    Connects to Alpaca IEX WebSocket for real-time QQQ trades + quotes.
    Free tier: real-time IEX exchange data. Sign up at alpaca.markets.
    """

    WS_URL = "wss://stream.data.alpaca.markets/v2/iex"

    def __init__(self, api_key: str, secret_key: str, buffer: TradeBuffer,
                 symbol: str = "QQQ"):
        self._api_key = api_key
        self._secret = secret_key
        self._buffer = buffer
        self._symbol = symbol
        self._quote = QuoteSnapshot()
        self._last_trade_price: float = 0.0
        self._ws = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False
        self._reconnect_delay = 1.0

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="alpaca-ws")
        self._thread.start()
        logger.info("Alpaca collector started for %s", self._symbol)

    def stop(self) -> None:
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _run_loop(self) -> None:
        import websocket as ws_lib
        while self._running:
            try:
                self._ws = ws_lib.WebSocketApp(
                    self.WS_URL,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                logger.warning("Alpaca WS error: %s", e)
            self._connected = False
            if self._running:
                time.sleep(min(self._reconnect_delay, 30))
                self._reconnect_delay = min(self._reconnect_delay * 2, 30)

    def _on_open(self, ws) -> None:
        auth_msg = {"action": "auth", "key": self._api_key, "secret": self._secret}
        ws.send(json.dumps(auth_msg))

    def _on_message(self, ws, message: str) -> None:
        try:
            msgs = json.loads(message)
            if not isinstance(msgs, list):
                msgs = [msgs]
            for msg in msgs:
                t = msg.get("T")
                if t == "success" and msg.get("msg") == "authenticated":
                    sub = {"action": "subscribe",
                           "trades": [self._symbol],
                           "quotes": [self._symbol]}
                    ws.send(json.dumps(sub))
                    self._connected = True
                    self._reconnect_delay = 1.0
                    logger.info("Alpaca authenticated & subscribed to %s trades+quotes", self._symbol)
                elif t == "q":
                    self._handle_quote(msg)
                elif t == "t":
                    self._handle_trade(msg)
        except Exception as e:
            logger.debug("Alpaca msg parse error: %s", e)

    def _handle_quote(self, msg: dict) -> None:
        self._quote.bid = msg.get("bp", self._quote.bid)
        self._quote.ask = msg.get("ap", self._quote.ask)
        self._quote.bid_size = msg.get("bs", self._quote.bid_size)
        self._quote.ask_size = msg.get("as", self._quote.ask_size)
        self._quote.timestamp = time.time()

    def _handle_trade(self, msg: dict) -> None:
        price = msg.get("p", 0)
        size = msg.get("s", 0)
        if price <= 0 or size <= 0:
            return

        side = self._classify_trade(price)
        nq_price = price * NQ_QQQ_RATIO

        trade = ClassifiedTrade(
            timestamp=time.time(),
            price_qqq=price,
            price_nq=nq_price,
            size=size,
            side=side,
            classification="quote" if self._quote.bid > 0 else "tick",
        )
        self._buffer.push(trade)
        self._last_trade_price = price

        # Also push to the global OrderFlowStore
        try:
            from data.orderflow import get_orderflow_store
            store = get_orderflow_store()
            store.push_trade(nq_price, size, side)
        except Exception:
            pass

    def _classify_trade(self, price: float) -> str:
        """Classify trade as buy/sell using quote rule (best) or tick rule (fallback)."""
        # Quote rule: trade at/above ask = buy, at/below bid = sell
        q = self._quote
        if q.bid > 0 and q.ask > 0 and (time.time() - q.timestamp) < 5:
            mid = (q.bid + q.ask) / 2.0
            if price >= q.ask:
                return "buy"
            if price <= q.bid:
                return "sell"
            # Between bid and ask: use midpoint
            return "buy" if price >= mid else "sell"

        # Tick rule: compare to last trade
        if self._last_trade_price > 0:
            if price > self._last_trade_price:
                return "buy"
            if price < self._last_trade_price:
                return "sell"
        return "buy"  # default

    def _on_error(self, ws, error) -> None:
        logger.debug("Alpaca WS error: %s", error)

    def _on_close(self, ws, close_status, close_msg) -> None:
        self._connected = False
        logger.debug("Alpaca WS closed: %s %s", close_status, close_msg)


# ---------------------------------------------------------------------------
# Finnhub WebSocket collector (backup)
# ---------------------------------------------------------------------------
class FinnhubCollector:
    """
    Connects to Finnhub WebSocket for real-time QQQ trades.
    Free tier: real-time US stock trades. Sign up at finnhub.io.
    No bid/ask quotes -- uses tick rule for trade classification.
    """

    WS_URL_TEMPLATE = "wss://ws.finnhub.io?token={token}"

    def __init__(self, api_key: str, buffer: TradeBuffer, symbol: str = "QQQ"):
        self._api_key = api_key
        self._buffer = buffer
        self._symbol = symbol
        self._last_price: float = 0.0
        self._ws = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._connected = False
        self._reconnect_delay = 1.0

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="finnhub-ws")
        self._thread.start()
        logger.info("Finnhub collector started for %s", self._symbol)

    def stop(self) -> None:
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass

    def _run_loop(self) -> None:
        import websocket as ws_lib
        url = self.WS_URL_TEMPLATE.format(token=self._api_key)
        while self._running:
            try:
                self._ws = ws_lib.WebSocketApp(
                    url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as e:
                logger.warning("Finnhub WS error: %s", e)
            self._connected = False
            if self._running:
                time.sleep(min(self._reconnect_delay, 30))
                self._reconnect_delay = min(self._reconnect_delay * 2, 30)

    def _on_open(self, ws) -> None:
        sub = {"type": "subscribe", "symbol": self._symbol}
        ws.send(json.dumps(sub))
        self._connected = True
        self._reconnect_delay = 1.0
        logger.info("Finnhub connected & subscribed to %s", self._symbol)

    def _on_message(self, ws, message: str) -> None:
        try:
            data = json.loads(message)
            if data.get("type") != "trade":
                return
            for t in data.get("data", []):
                price = t.get("p", 0)
                vol = t.get("v", 0)
                if price <= 0 or vol <= 0:
                    continue
                side = self._classify_tick(price)
                nq_price = price * NQ_QQQ_RATIO
                trade = ClassifiedTrade(
                    timestamp=t.get("t", time.time() * 1000) / 1000.0,
                    price_qqq=price,
                    price_nq=nq_price,
                    size=vol,
                    side=side,
                    classification="tick",
                )
                self._buffer.push(trade)
                self._last_price = price

                try:
                    from data.orderflow import get_orderflow_store
                    get_orderflow_store().push_trade(nq_price, vol, side)
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Finnhub msg parse error: %s", e)

    def _classify_tick(self, price: float) -> str:
        if self._last_price > 0:
            if price > self._last_price:
                return "buy"
            if price < self._last_price:
                return "sell"
        return "buy"

    def _on_error(self, ws, error) -> None:
        logger.debug("Finnhub WS error: %s", error)

    def _on_close(self, ws, close_status, close_msg) -> None:
        self._connected = False
        logger.debug("Finnhub WS closed")


# ---------------------------------------------------------------------------
# Manager: picks best available source, exposes unified buffer
# ---------------------------------------------------------------------------
class DataCollectorManager:
    """
    Manages multiple real-time data collectors.
    Tries Alpaca first (trades + quotes), Finnhub second (trades only).
    Falls back gracefully if no API keys are configured.
    """

    def __init__(self):
        self.buffer = TradeBuffer(maxlen=50_000)
        self._alpaca: AlpacaCollector | None = None
        self._finnhub: FinnhubCollector | None = None
        self._started = False

    @property
    def source(self) -> str:
        if self._alpaca and self._alpaca.connected:
            return "Alpaca (real-time trades+quotes)"
        if self._finnhub and self._finnhub.connected:
            return "Finnhub (real-time trades)"
        return "none"

    @property
    def connected(self) -> bool:
        return (
            (self._alpaca is not None and self._alpaca.connected)
            or (self._finnhub is not None and self._finnhub.connected)
        )

    def start(self,
              alpaca_key: str = "",
              alpaca_secret: str = "",
              finnhub_key: str = "") -> str:
        """Start collectors. Returns description of what started."""
        if self._started:
            return self.source
        self._started = True
        started = []

        if alpaca_key and alpaca_secret:
            self._alpaca = AlpacaCollector(alpaca_key, alpaca_secret, self.buffer)
            self._alpaca.start()
            started.append("Alpaca (QQQ trades+quotes)")

        if finnhub_key:
            self._finnhub = FinnhubCollector(finnhub_key, self.buffer)
            self._finnhub.start()
            started.append("Finnhub (QQQ trades)")

        if not started:
            logger.info("No real-time API keys configured. Using candle proxy for order flow.")
            return "none (no API keys)"

        desc = " + ".join(started)
        logger.info("Real-time data collectors started: %s", desc)
        return desc

    def stop(self) -> None:
        if self._alpaca:
            self._alpaca.stop()
        if self._finnhub:
            self._finnhub.stop()
        self._started = False


# Global singleton
_manager: DataCollectorManager | None = None


def get_collector_manager() -> DataCollectorManager:
    global _manager
    if _manager is None:
        _manager = DataCollectorManager()
    return _manager
