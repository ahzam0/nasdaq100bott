"""
Tradovate real-time market data via WebSocket (delay-free when account has market data).
Requires: TRADOVATE_NAME, TRADOVATE_PASSWORD, TRADOVATE_APP_ID, TRADOVATE_APP_VERSION, TRADOVATE_CID, TRADOVATE_SEC.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Demo vs Live
TRADOVATE_AUTH_URL_LIVE = "https://live.tradovateapi.com/v1/auth/accesstokenrequest"
TRADOVATE_AUTH_URL_DEMO = "https://demo.tradovateapi.com/v1/auth/accesstokenrequest"
TRADOVATE_WS_MD_LIVE = "wss://md.tradovateapi.com/v1/websocket"
TRADOVATE_WS_MD_DEMO = "wss://demo.tradovateapi.com/v1/websocket"


def get_tradovate_tokens(
    name: str,
    password: str,
    app_id: str,
    app_version: str,
    cid: int | str,
    sec: str,
    demo: bool = True,
) -> tuple[Optional[str], Optional[str]]:
    """Get accessToken and mdAccessToken from Tradovate REST auth."""
    url = TRADOVATE_AUTH_URL_DEMO if demo else TRADOVATE_AUTH_URL_LIVE
    payload = {
        "name": name,
        "password": password,
        "appId": app_id,
        "appVersion": app_version,
        "cid": int(cid) if isinstance(cid, str) and cid.isdigit() else cid,
        "sec": sec,
    }
    try:
        import requests
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        if data.get("errorText"):
            logger.warning("Tradovate auth error: %s", data["errorText"])
            return None, None
        return data.get("accessToken"), data.get("mdAccessToken")
    except Exception as e:
        logger.warning("Tradovate auth failed: %s", e)
        return None, None


class TradovateMDClient:
    """
    WebSocket client for Tradovate market data. Keeps last_price updated from real-time quote stream.
    Run start() in a thread; call get_last_price() from any thread.
    """

    def __init__(
        self,
        md_access_token: str,
        symbol: str = "NQ",
        demo: bool = True,
    ):
        self._md_token = md_access_token
        self._symbol = symbol
        self._demo = demo
        self._ws_url = TRADOVATE_WS_MD_DEMO if demo else TRADOVATE_WS_MD_LIVE
        self._last_price: Optional[float] = None
        self._last_bid: Optional[float] = None
        self._last_ask: Optional[float] = None
        self._connected = False
        self._ws = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def get_last_price(self) -> Optional[float]:
        """Return last traded price from stream (delay-free)."""
        return self._last_price or self._last_bid or self._last_ask

    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """Start WebSocket in a daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_ws, daemon=True)
        self._thread.start()
        # Give a moment to connect and receive first quote
        for _ in range(25):
            if self._last_price is not None or self._connected:
                break
            time.sleep(0.2)

    def stop(self) -> None:
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._connected = False

    def _run_ws(self) -> None:
        try:
            import websocket
        except ImportError:
            logger.warning("websocket-client not installed. pip install websocket-client")
            return
        while not self._stop.is_set():
            try:
                self._ws = websocket.WebSocketApp(
                    self._ws_url,
                    on_open=self._on_open,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                )
                self._ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                logger.debug("Tradovate MD WS error: %s", e)
            if self._stop.is_set():
                break
            time.sleep(2)

    def _on_open(self, _) -> None:
        # Tradovate: send authorize\n0\n\n{mdAccessToken}
        msg = f"authorize\n0\n\n{self._md_token}"
        try:
            self._ws.send(msg)
            logger.info("Tradovate MD: authorize sent for %s", self._symbol)
        except Exception as e:
            logger.warning("Tradovate MD send auth failed: %s", e)

    def _on_message(self, _, data: str) -> None:
        if not data:
            return
        # Heartbeat
        if data == "o" or data == "[]":
            try:
                if data == "[]":
                    self._ws.send("[]")
            except Exception:
                pass
            return
        # Array response: a[{...}, ...]
        if data.startswith("a["):
            try:
                arr = json.loads(data[1:])
                if not isinstance(arr, list):
                    return
                for item in arr:
                    if not isinstance(item, dict):
                        continue
                    # Auth response (request id 0)
                    if item.get("i") == 0:
                        if item.get("s") == 200:
                            self._connected = True
                            # Subscribe to quote
                            sub = json.dumps({"symbol": self._symbol})
                            try:
                                self._ws.send(f"md/subscribeQuote\n1\n{sub}")
                            except Exception as e:
                                logger.warning("Tradovate subscribeQuote failed: %s", e)
                        else:
                            logger.warning("Tradovate MD auth failed: %s", item)
                    # Quote update (e.g. d.last, d.bid, d.ask)
                    d = item.get("d")
                    if isinstance(d, dict):
                        # Common field names for last price
                        last = d.get("last") or d.get("lastPrice") or d.get("close")
                        if last is not None:
                            try:
                                self._last_price = float(last)
                            except (TypeError, ValueError):
                                pass
                        bid = d.get("bid")
                        if bid is not None:
                            try:
                                self._last_bid = float(bid)
                            except (TypeError, ValueError):
                                pass
                        ask = d.get("ask")
                        if ask is not None:
                            try:
                                self._last_ask = float(ask)
                            except (TypeError, ValueError):
                                pass
            except json.JSONDecodeError:
                pass
            return
        try:
            obj = json.loads(data)
            if isinstance(obj, dict):
                d = obj.get("d", obj)
                last = (d.get("last") or d.get("lastPrice") or d.get("close") if isinstance(d, dict) else None)
                if last is not None:
                    self._last_price = float(last)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    def _on_error(self, _, error: Exception) -> None:
        logger.debug("Tradovate MD WS error: %s", error)

    def _on_close(self, _, status, msg) -> None:
        self._connected = False
        logger.debug("Tradovate MD WS closed: %s %s", status, msg)


def create_tradovate_md_client(
    name: str = "",
    password: str = "",
    app_id: str = "",
    app_version: str = "1.0",
    cid: str = "0",
    sec: str = "",
    md_access_token: str = "",
    symbol: str = "NQ",
    demo: bool = True,
) -> Optional[TradovateMDClient]:
    """Create and start a Tradovate MD client. Uses md_access_token if set, else gets tokens via name/password."""
    token = md_access_token
    if not token and name and password and app_id and sec:
        _, token = get_tradovate_tokens(name, password, app_id, app_version, cid, sec, demo=demo)
    if not token:
        logger.warning("Tradovate MD: no mdAccessToken available")
        return None
    client = TradovateMDClient(md_access_token=token, symbol=symbol, demo=demo)
    client.start()
    return client
