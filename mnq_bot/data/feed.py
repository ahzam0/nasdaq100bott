"""
Market data feed: 1-min and 15-min MNQ candles.
Abstract interface; implement with NinjaTrader, IB, Tradovate, or mock for testing.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class Candle:
    """Single OHLCV candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def to_series(self) -> pd.Series:
        return pd.Series({
            "open": self.open, "high": self.high, "low": self.low,
            "close": self.close, "volume": self.volume
        }, name=self.timestamp)


def candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
    """Convert list of Candle to DataFrame with DatetimeIndex."""
    if not candles:
        return pd.DataFrame()
    rows = [
        {
            "open": c.open, "high": c.high, "low": c.low,
            "close": c.close, "volume": c.volume
        }
        for c in candles
    ]
    df = pd.DataFrame(rows, index=[c.timestamp for c in candles])
    df.index.name = "timestamp"
    return df


class MarketDataFeed(ABC):
    """Abstract market data feed for MNQ."""

    @abstractmethod
    def get_1m_candles(self, count: int = 100) -> pd.DataFrame:
        """Return last N 1-minute candles. Index = datetime (UTC or EST as configured)."""
        pass

    @abstractmethod
    def get_15m_candles(self, count: int = 50) -> pd.DataFrame:
        """Return last N 15-minute candles."""
        pass

    @abstractmethod
    def get_current_price(self) -> Optional[float]:
        """Current last/bid price for trailing and alerts."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """True if feed is connected and receiving data."""
        pass


class MockDataFeed(MarketDataFeed):
    """
    Mock feed for development and testing.
    Generates deterministic 1m/15m bars from a seed.
    """

    def __init__(self, seed_price: float = 19000.0):
        self._seed = seed_price
        self._connected = True
        self._current = seed_price

    def get_1m_candles(self, count: int = 100) -> pd.DataFrame:
        import numpy as np
        np.random.seed(42)
        now = pd.Timestamp.utcnow().floor("1min")
        index = pd.date_range(end=now, periods=count, freq="1min")
        returns = np.random.randn(count).cumsum() * 2
        close = self._seed + returns
        high = close + np.abs(np.random.randn(count) * 3)
        low = close - np.abs(np.random.randn(count) * 3)
        open_ = np.roll(close, 1)
        open_[0] = self._seed
        df = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "volume": np.random.randint(100, 5000, count)
        }, index=index)
        df.index.name = "timestamp"
        if len(df) > 0:
            self._current = float(df["close"].iloc[-1])
        return df

    def get_15m_candles(self, count: int = 50) -> pd.DataFrame:
        import numpy as np
        np.random.seed(43)
        now = pd.Timestamp.utcnow().floor("15min")
        index = pd.date_range(end=now, periods=count, freq="15min")
        returns = np.random.randn(count).cumsum() * 5
        close = self._seed + returns
        high = close + np.abs(np.random.randn(count) * 5)
        low = close - np.abs(np.random.randn(count) * 5)
        open_ = np.roll(close, 1)
        open_[0] = self._seed
        df = pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close,
            "volume": np.random.randint(1000, 20000, count)
        }, index=index)
        df.index.name = "timestamp"
        return df

    def get_current_price(self) -> Optional[float]:
        return self._current

    def is_connected(self) -> bool:
        return self._connected


class YahooFinanceFeed(MarketDataFeed):
    """
    Live price feed from Yahoo Finance (free, no API key).
    Uses NQ=F (E-mini Nasdaq-100, same as MNQ). Best available price; free tier may be delayed.
    """

    # Try NQ=F first; fallbacks if rate-limited or region-blocked
    SYMBOLS = ("NQ=F", "^NDX", "ES=F", "^IXIC")

    def __init__(self):
        self._symbol: Optional[str] = None
        self._connected = False
        self._last_1m: pd.DataFrame = pd.DataFrame()
        self._last_15m: pd.DataFrame = pd.DataFrame()

    def _ensure_symbol(self) -> bool:
        if self._symbol is not None:
            return True
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed. Run: pip install yfinance")
            return False
        for sym in self.SYMBOLS:
            try:
                t = yf.Ticker(sym)
                info = t.fast_info
                if getattr(info, "lastPrice", None) is not None:
                    self._symbol = sym
                    self._connected = True
                    logger.info("Yahoo Finance feed using symbol %s", sym)
                    return True
                h = t.history(period="5d", interval="1d")
                if h is not None and not h.empty:
                    self._symbol = sym
                    self._connected = True
                    logger.info("Yahoo Finance feed using symbol %s", sym)
                    return True
            except Exception as e:
                logger.debug("Yahoo Finance %s failed: %s", sym, e)
        return False

    def get_1m_candles(self, count: int = 100) -> pd.DataFrame:
        if not self._ensure_symbol():
            return pd.DataFrame()
        try:
            from backtest.live_data import fetch_yfinance_1m
            df = fetch_yfinance_1m(symbol=self._symbol, period="7d")
            if df.empty or len(df) < 2:
                return self._last_1m.tail(count).copy() if not self._last_1m.empty else pd.DataFrame()
            self._last_1m = df
            return df.tail(count).copy()
        except Exception as e:
            logger.warning("Yahoo 1m fetch failed: %s", e)
            if not self._last_1m.empty:
                return self._last_1m.tail(count).copy()
            return pd.DataFrame()

    def get_15m_candles(self, count: int = 50) -> pd.DataFrame:
        if not self._ensure_symbol():
            return pd.DataFrame()
        try:
            from backtest.live_data import fetch_yfinance_15m
            df = fetch_yfinance_15m(symbol=self._symbol, period="7d")
            if df.empty or len(df) < 2:
                return self._last_15m.tail(count).copy() if not self._last_15m.empty else pd.DataFrame()
            self._last_15m = df
            return df.tail(count).copy()
        except Exception as e:
            logger.warning("Yahoo 15m fetch failed: %s", e)
            if not self._last_15m.empty:
                return self._last_15m.tail(count).copy()
            return pd.DataFrame()

    def get_current_price(self) -> Optional[float]:
        if not self._ensure_symbol():
            return None
        try:
            import yfinance as yf
            t = yf.Ticker(self._symbol)
            price = getattr(t.fast_info, "lastPrice", None)
            if price is not None and not (isinstance(price, float) and (price != price)):
                return float(price)
            # Fallback: last close from 1m
            if not self._last_1m.empty:
                return float(self._last_1m["close"].iloc[-1])
            hist = t.history(period="1d", interval="1m", prepost=True)
            if hist is not None and not hist.empty and "Close" in hist.columns:
                return float(hist["Close"].iloc[-1])
        except Exception as e:
            logger.debug("Yahoo current price failed: %s", e)
            if not self._last_1m.empty:
                return float(self._last_1m["close"].iloc[-1])
        return None

    def is_connected(self) -> bool:
        if not self._connected:
            self._ensure_symbol()
        return self._connected


class YahooWSFeed(MarketDataFeed):
    """
    Free minimal-delay price from Yahoo WebSocket (QQQ stream, scaled to NQ equivalent).
    No API key. 1m/15m candles from Yahoo REST.
    """

    def __init__(self, ws_client, yahoo_feed: Optional["YahooFinanceFeed"] = None):
        self._ws = ws_client
        self._yahoo = yahoo_feed or YahooFinanceFeed()
        self._connected = ws_client.is_connected() if ws_client else False

    def get_1m_candles(self, count: int = 100) -> pd.DataFrame:
        return self._yahoo.get_1m_candles(count)

    def get_15m_candles(self, count: int = 50) -> pd.DataFrame:
        return self._yahoo.get_15m_candles(count)

    def get_current_price(self) -> Optional[float]:
        p = self._ws.get_nq_equivalent_price() if self._ws else None
        if p is not None:
            self._connected = True
            return p
        return self._yahoo.get_current_price()

    def is_connected(self) -> bool:
        return (self._ws and self._ws.is_connected()) or self._yahoo.is_connected()


class TradovateRealtimeFeed(MarketDataFeed):
    """
    Delay-free price from Tradovate WebSocket; 1m/15m candles from Yahoo (for levels/setups).
    Set TRADOVATE_USE_REALTIME_MD=True and Tradovate credentials in config.
    """

    def __init__(self, md_client, yahoo_feed: Optional["YahooFinanceFeed"] = None):
        self._md = md_client
        self._yahoo = yahoo_feed or YahooFinanceFeed()
        self._connected = md_client.is_connected() if md_client else False

    def get_1m_candles(self, count: int = 100) -> pd.DataFrame:
        return self._yahoo.get_1m_candles(count)

    def get_15m_candles(self, count: int = 50) -> pd.DataFrame:
        return self._yahoo.get_15m_candles(count)

    def get_current_price(self) -> Optional[float]:
        p = self._md.get_last_price() if self._md else None
        if p is not None:
            self._connected = True
            return p
        return self._yahoo.get_current_price()

    def is_connected(self) -> bool:
        return (self._md and self._md.is_connected()) or self._yahoo.is_connected()


class LocalAPIFeed(MarketDataFeed):
    """
    Feed that uses our local Price API (api/price_server.py).
    Start the server with: python -m api.price_server
    Cached responses minimize delay; swap API backend for real-time when available.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:5001", timeout: float = 10.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._connected = False
        self._last_price: Optional[float] = None
        self._last_1m: pd.DataFrame = pd.DataFrame()
        self._last_15m: pd.DataFrame = pd.DataFrame()

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        try:
            import requests
            r = requests.get(f"{self._base}{path}", timeout=self._timeout, params=params or {})
            if r.status_code == 200:
                self._connected = True
                return r.json()
        except Exception as e:
            logger.debug("Price API %s failed: %s", path, e)
        return None

    def _candles_json_to_df(self, data: list) -> pd.DataFrame:
        if not data:
            return pd.DataFrame()
        rows = []
        index = []
        for c in data:
            rows.append({
                "open": float(c["open"]), "high": float(c["high"]),
                "low": float(c["low"]), "close": float(c["close"]),
                "volume": int(c.get("volume", 0)),
            })
            try:
                index.append(pd.to_datetime(c["timestamp"]))
            except Exception:
                pass
        df = pd.DataFrame(rows)
        if len(index) == len(rows):
            df.index = pd.DatetimeIndex(index)
        df.index.name = "timestamp"
        return df

    def get_1m_candles(self, count: int = 100) -> pd.DataFrame:
        out = self._get("/candles/1m", {"count": count})
        if out and "candles" in out:
            df = self._candles_json_to_df(out["candles"])
            if not df.empty:
                self._last_1m = df
                return df
        return self._last_1m.tail(count).copy() if not self._last_1m.empty else pd.DataFrame()

    def get_15m_candles(self, count: int = 50) -> pd.DataFrame:
        out = self._get("/candles/15m", {"count": count})
        if out and "candles" in out:
            df = self._candles_json_to_df(out["candles"])
            if not df.empty:
                self._last_15m = df
                return df
        return self._last_15m.tail(count).copy() if not self._last_15m.empty else pd.DataFrame()

    def get_current_price(self) -> Optional[float]:
        out = self._get("/price")
        if out and "price" in out:
            p = float(out["price"])
            self._last_price = p
            return p
        return self._last_price

    def is_connected(self) -> bool:
        return self._connected


def get_feed(broker: str = "paper", use_live_feed: bool = True, price_api_url: Optional[str] = None) -> MarketDataFeed:
    """Factory: Tradovate realtime (delay-free) if enabled; else price_api_url; else Yahoo (free, delayed)."""
    try:
        from config import (
            TRADOVATE_USE_REALTIME_MD,
            TRADOVATE_NAME,
            TRADOVATE_PASSWORD,
            TRADOVATE_APP_ID,
            TRADOVATE_APP_VERSION,
            TRADOVATE_CID,
            TRADOVATE_SEC,
            TRADOVATE_DEMO,
            TRADOVATE_MD_SYMBOL,
            TRADOVATE_ACCESS_TOKEN,
        )
        if (broker == "tradovate" and TRADOVATE_USE_REALTIME_MD and
                (TRADOVATE_ACCESS_TOKEN or (TRADOVATE_NAME and TRADOVATE_PASSWORD and TRADOVATE_APP_ID and TRADOVATE_SEC))):
            from data.tradovate_realtime import create_tradovate_md_client
            md_client = create_tradovate_md_client(
                name=TRADOVATE_NAME,
                password=TRADOVATE_PASSWORD,
                app_id=TRADOVATE_APP_ID,
                app_version=TRADOVATE_APP_VERSION,
                cid=TRADOVATE_CID,
                sec=TRADOVATE_SEC,
                md_access_token=TRADOVATE_ACCESS_TOKEN or "",
                symbol=TRADOVATE_MD_SYMBOL,
                demo=TRADOVATE_DEMO,
            )
            if md_client:
                logger.info("Using Tradovate real-time feed (delay-free)")
                return TradovateRealtimeFeed(md_client=md_client)
    except Exception as e:
        logger.debug("Tradovate realtime feed skipped: %s", e)
    # Free minimal-delay: our Yahoo WebSocket feed (QQQ stream -> NQ equivalent). Uses singleton to avoid thread exhaustion.
    try:
        from config import get_use_yahoo_ws_realtime, YAHOO_WS_QQQ_TO_NQ_RATIO
        if get_use_yahoo_ws_realtime():
            from data.yahoo_ws_realtime import get_or_create_yahoo_ws_client
            ws_client = get_or_create_yahoo_ws_client(qqq_to_nq_ratio=YAHOO_WS_QQQ_TO_NQ_RATIO, auto_start=False)
            if ws_client:
                logger.info("Using Yahoo WebSocket feed (free, minimal delay)")
                return YahooWSFeed(ws_client=ws_client)
    except Exception as e:
        logger.debug("Yahoo WS feed skipped: %s", e)
    if price_api_url and str(price_api_url).strip():
        try:
            return LocalAPIFeed(base_url=str(price_api_url).strip())
        except Exception as e:
            logger.warning("Price API feed failed, falling back: %s", e)
    if use_live_feed:
        try:
            return YahooFinanceFeed()
        except Exception as e:
            logger.warning("Live feed failed, falling back to mock: %s", e)
    if broker in ("paper", "ninjatrader", "tradovate"):
        return MockDataFeed()
    return MockDataFeed()


def start_live_feed_session() -> None:
    """Start WebSocket/live feed when session begins (e.g. 7:00 EST). Idempotent."""
    try:
        from config import BROKER, USE_LIVE_FEED, PRICE_API_URL
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        if getattr(feed, "_ws", None) is not None and hasattr(feed._ws, "start"):
            feed._ws.start()
            logger.info("Live feed session started (Yahoo WebSocket)")
        if getattr(feed, "_md", None) is not None and hasattr(feed._md, "start"):
            feed._md.start()
            logger.info("Live feed session started (Tradovate MD)")
    except Exception as e:
        logger.debug("start_live_feed_session: %s", e)


def end_live_feed_session() -> None:
    """Stop WebSocket/live feed when session ends (e.g. 11:00 EST). Puts feed in rest."""
    try:
        from config import BROKER, USE_LIVE_FEED, PRICE_API_URL
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        if getattr(feed, "_ws", None) is not None and hasattr(feed._ws, "stop"):
            feed._ws.stop()
            logger.info("Live feed session ended (Yahoo WebSocket — rest)")
        if getattr(feed, "_md", None) is not None and hasattr(feed._md, "stop"):
            feed._md.stop()
            logger.info("Live feed session ended (Tradovate MD — rest)")
    except Exception as e:
        logger.debug("end_live_feed_session: %s", e)
