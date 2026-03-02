"""
Polygon.io real-time futures trades → order flow API bridge.
Subscribes to Polygon WebSocket futures trade stream (real market trades)
and pushes each trade to the local order flow server (POST /orderflow/push).

Requires: POLYGON_API_KEY (get free at polygon.io). No Tradovate.
Run: python -m data.polygon_orderflow_bridge   or set MNQ_ORDERFLOW_FROM_POLYGON=true when starting orderflow_server.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

POLYGON_WS_FUTURES = "wss://socket.polygon.io/futures"
DEFAULT_ORDERFLOW_PUSH_URL = "http://127.0.0.1:5002/orderflow/push"


def _push_trade(push_url: str, price: float, size: int, side: str) -> bool:
    """POST one trade to the order flow API."""
    try:
        body = json.dumps({"price": price, "size": size, "side": side}).encode("utf-8")
        req = urllib.request.Request(
            push_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.getcode() == 200
    except Exception as e:
        logger.debug("Order flow push failed: %s", e)
        return False


def _normalize_price(p: float, sym: str) -> float:
    """Polygon sometimes sends price in cents or scaled. NQ/ES are index points."""
    if p > 0 and p < 1e6:
        return float(p)
    if p >= 1e6:
        return p / 100.0
    return float(p)


def run_polygon_orderflow_bridge(
    api_key: str,
    ticker: str = "MNQ",
    orderflow_push_url: str = DEFAULT_ORDERFLOW_PUSH_URL,
) -> None:
    """
    Connect to Polygon futures WebSocket, subscribe to trades for ticker, push each to order flow API.
    Blocks until stopped or connection fails.
    """
    try:
        import websocket
    except ImportError:
        logger.error("websocket-client not installed. pip install websocket-client")
        return
    last_price: Optional[float] = None
    push_count = [0]
    authenticated = [False]

    def _on_open(_) -> None:
        auth_msg = json.dumps({"action": "auth", "params": api_key})
        ws.send(auth_msg)
        logger.info("Polygon order flow bridge: auth sent for %s", ticker)

    def _on_message(_, data: str) -> None:
        nonlocal last_price
        if not data:
            return
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            return
        if not isinstance(msg, list):
            msg = [msg]
        for item in msg:
            if not isinstance(item, dict):
                continue
            ev = item.get("ev")
            # Auth response
            if ev is None and "status" in item:
                if item.get("status") == "auth_success" or item.get("message") == "authenticated":
                    authenticated[0] = True
                    sub_msg = json.dumps({"action": "subscribe", "params": f"T.{ticker}"})
                    ws.send(sub_msg)
                    logger.info("Polygon order flow bridge: subscribed to T.%s", ticker)
                else:
                    logger.warning("Polygon auth response: %s", item)
                continue
            # Trade
            if ev == "T":
                p = item.get("p")
                s = item.get("s", 1)
                if p is None or s is None:
                    continue
                price = _normalize_price(float(p), item.get("sym", ticker))
                size = max(1, int(s))
                side = "buy" if (last_price is None or price >= last_price) else "sell"
                last_price = price
                if _push_trade(orderflow_push_url, price, size, side):
                    push_count[0] += 1
                    if push_count[0] <= 5 or push_count[0] % 500 == 0:
                        logger.info("Order flow push #%s: %s %.2f x %s", push_count[0], side, price, size)
                continue
            if ev == "Q":
                pass

    def _on_error(_, err: Exception) -> None:
        logger.debug("Polygon order flow WS error: %s", err)

    def _on_close(_, status, msg) -> None:
        logger.info("Polygon order flow bridge closed: %s %s", status, msg)

    ws = websocket.WebSocketApp(
        POLYGON_WS_FUTURES,
        on_open=_on_open,
        on_message=_on_message,
        on_error=_on_error,
        on_close=_on_close,
    )
    logger.info("Polygon order flow bridge starting (ticker=%s, push_url=%s)", ticker, orderflow_push_url)
    while True:
        try:
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            logger.debug("Polygon bridge run_forever: %s", e)
        time.sleep(2)


def main() -> None:
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from config import ORDERFLOW_API_URL
    key = os.getenv("POLYGON_API_KEY", "").strip()
    if not key:
        logger.error("POLYGON_API_KEY not set. Get a key at polygon.io")
        sys.exit(1)
    ticker = os.getenv("MNQ_ORDERFLOW_POLYGON_TICKER", "MNQ").strip()
    push_url = (ORDERFLOW_API_URL or "http://127.0.0.1:5002").rstrip("/") + "/orderflow/push"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    try:
        run_polygon_orderflow_bridge(api_key=key, ticker=ticker, orderflow_push_url=push_url)
    except KeyboardInterrupt:
        logger.info("Polygon order flow bridge stopped by user")


if __name__ == "__main__":
    main()
