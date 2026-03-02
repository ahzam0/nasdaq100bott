"""
Tradovate real-time tick stream → order flow API bridge.
Subscribes to md/getChart Tick data (real market trades) and pushes each trade
to the local order flow server (POST /orderflow/push) for zero-delay order flow in the app.

Requires: Tradovate credentials with market data, and order flow server running.
Run: python -m data.tradovate_orderflow_bridge   (or set MNQ_ORDERFLOW_FROM_TRADOVATE=true and start from orderflow_server)
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from typing import Optional

from data.tradovate_realtime import (
    TRADOVATE_WS_MD_DEMO,
    TRADOVATE_WS_MD_LIVE,
    get_tradovate_tokens,
)

logger = logging.getLogger(__name__)

# NQ/MNQ tick size in points
NQ_TICK_SIZE = 0.25
DEFAULT_ORDERFLOW_PUSH_URL = "http://127.0.0.1:5002/orderflow/push"


def _push_trade(push_url: str, price: float, size: int, side: str) -> bool:
    """POST one trade to the order flow API. Returns True on success."""
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


def _infer_side(tick: dict, packet_bp: float, packet_ts: float, last_price: Optional[float]) -> str:
    """Infer buy vs sell from tick: use bid/ask if present, else tick rule (price vs last)."""
    p = tick.get("p", 0)
    price = (packet_bp + p) * (packet_ts if packet_ts > 0 else NQ_TICK_SIZE)
    b = tick.get("b")
    a = tick.get("a")
    if a is not None and b is not None:
        ask = (packet_bp + a) * (packet_ts if packet_ts > 0 else NQ_TICK_SIZE)
        bid = (packet_bp + b) * (packet_ts if packet_ts > 0 else NQ_TICK_SIZE)
        if price >= ask:
            return "buy"
        if price <= bid:
            return "sell"
    if last_price is not None:
        return "buy" if price >= last_price else "sell"
    return "buy"


def run_tradovate_orderflow_bridge(
    md_access_token: str,
    symbol: str = "NQ",
    demo: bool = True,
    orderflow_push_url: str = DEFAULT_ORDERFLOW_PUSH_URL,
    tick_size: float = NQ_TICK_SIZE,
) -> None:
    """
    Connect to Tradovate MD WebSocket, subscribe to Tick stream, push each trade to order flow API.
    Blocks until stopped (Ctrl+C) or connection fails permanently.
    """
    try:
        import websocket
    except ImportError:
        logger.error("websocket-client not installed. pip install websocket-client")
        return
    ws_url = TRADOVATE_WS_MD_DEMO if demo else TRADOVATE_WS_MD_LIVE
    request_id = [0]
    last_price: Optional[float] = None
    chart_subscription_id: Optional[int] = None
    eoh = [False]
    push_count = [0]
    stop = threading.Event()

    def send(msg: str) -> None:
        if ws and ws.sock and ws.sock.connected:
            ws.send(msg)

    def _on_open(_) -> None:
        auth_msg = f"authorize\n{request_id[0]}\n\n{md_access_token}"
        send(auth_msg)
        request_id[0] += 1
        logger.info("Tradovate order flow bridge: authorize sent for %s", symbol)

    def _on_message(_, data: str) -> None:
        nonlocal last_price, chart_subscription_id
        if not data:
            return
        if data == "o":
            return
        if data == "[]":
            send("[]")
            return
        if not data.startswith("a["):
            return
        try:
            arr = json.loads(data[1:])
        except json.JSONDecodeError:
            return
        if not isinstance(arr, list):
            return
        for item in arr:
            if not isinstance(item, dict):
                continue
            i = item.get("i")
            s = item.get("s")
            d = item.get("d")
            # Auth response
            if i == 0:
                if s == 200:
                    body = {
                        "symbol": symbol,
                        "chartDescription": {
                            "underlyingType": "Tick",
                            "elementSize": 1,
                            "elementSizeUnit": "UnderlyingUnits",
                            "withHistogram": False,
                        },
                        "timeRange": {"asMuchAsElements": 2},
                    }
                    send(f"md/getChart\n{request_id[0]}\n\n{json.dumps(body)}")
                    request_id[0] += 1
                    logger.info("Tradovate order flow bridge: md/getChart Tick sent")
                else:
                    logger.warning("Tradovate MD auth failed: %s", item)
                continue
            # getChart response: subscription id (i=1)
            if i == 1 and d and isinstance(d, dict) and "realtimeId" in d:
                chart_subscription_id = d.get("realtimeId")
                logger.info("Tradovate order flow bridge: chart subscription id=%s", chart_subscription_id)
            # End of history
            if d and isinstance(d, dict) and d.get("eoh") is True:
                eoh[0] = True
                logger.info("Tradovate order flow bridge: real-time tick stream active")
                continue
            # Chart data: d.charts[] with .bp, .bt, .ts, .tks[]
            if d and isinstance(d, dict) and "charts" in d:
                for chart in d.get("charts", []):
                    if not isinstance(chart, dict):
                        continue
                    bp = float(chart.get("bp", 0))
                    ts = float(chart.get("ts", tick_size) or tick_size)
                    tks = chart.get("tks") or []
                    for tick in tks:
                        if not isinstance(tick, dict):
                            continue
                        rel_p = tick.get("p", 0)
                        size = int(tick.get("s", 1))
                        if size < 1:
                            size = 1
                        price = (bp + rel_p) * ts
                        side = _infer_side(tick, bp, ts, last_price)
                        if _push_trade(orderflow_push_url, price, size, side):
                            push_count[0] += 1
                            if push_count[0] <= 5 or push_count[0] % 500 == 0:
                                logger.info("Order flow push #%s: %s %.2f x %s", push_count[0], side, price, size)
                        last_price = price

    def _on_error(_, err: Exception) -> None:
        logger.debug("Tradovate order flow WS error: %s", err)

    def _on_close(_, status, msg) -> None:
        logger.info("Tradovate order flow bridge closed: %s %s", status, msg)

    ws = websocket.WebSocketApp(
        ws_url,
        on_open=_on_open,
        on_message=_on_message,
        on_error=_on_error,
        on_close=_on_close,
    )
    logger.info("Tradovate order flow bridge starting (symbol=%s, push_url=%s)", symbol, orderflow_push_url)
    while not stop.is_set():
        try:
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            logger.debug("Tradovate order flow bridge run_forever: %s", e)
        if stop.is_set():
            break
        time.sleep(2)


def main() -> None:
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parent.parent
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from config import (
        ORDERFLOW_API_URL,
        TRADOVATE_NAME,
        TRADOVATE_PASSWORD,
        TRADOVATE_APP_ID,
        TRADOVATE_APP_VERSION,
        TRADOVATE_CID,
        TRADOVATE_SEC,
        TRADOVATE_DEMO,
        TRADOVATE_MD_SYMBOL,
    )
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    push_url = (ORDERFLOW_API_URL or "http://127.0.0.1:5002").rstrip("/") + "/orderflow/push"
    token = None
    if TRADOVATE_NAME and TRADOVATE_PASSWORD and TRADOVATE_APP_ID and TRADOVATE_SEC:
        _, token = get_tradovate_tokens(
            TRADOVATE_NAME, TRADOVATE_PASSWORD, TRADOVATE_APP_ID, TRADOVATE_APP_VERSION,
            TRADOVATE_CID or "0", TRADOVATE_SEC, demo=TRADOVATE_DEMO,
        )
    if not token:
        logger.error("Tradovate credentials missing or auth failed. Set TRADOVATE_NAME, TRADOVATE_PASSWORD, TRADOVATE_APP_ID, TRADOVATE_SEC.")
        sys.exit(1)
    run_tradovate_orderflow_bridge(
        md_access_token=token,
        symbol=TRADOVATE_MD_SYMBOL or "NQ",
        demo=TRADOVATE_DEMO,
        orderflow_push_url=push_url,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Tradovate order flow bridge stopped by user")
