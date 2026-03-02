"""
Live Order Flow API – own server to fetch order flow with minimal delay.
- GET /orderflow/summary – delta, imbalance, last update (for strategy).
- POST /orderflow/push – push trades from your feed (broker, Rithmic, etc.) for zero-delay.
- Optional: simulated delta from last candle (has delay; use for testing only).

Run: python -m api.orderflow_server   (default port 5002)
For zero delay: feed trades via POST /orderflow/push from your real-time source.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import sys
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from flask import Flask, jsonify, request
except ImportError:
    raise ImportError("Install Flask: pip install flask")

from data.orderflow import get_orderflow_store, OrderFlowSummary

app = Flask(__name__)
ORDERFLOW_TTL_SEC = float(os.getenv("MNQ_ORDERFLOW_CACHE_TTL", "2"))  # Summary considered fresh for 2s


def _store() -> "OrderFlowStore":
    return get_orderflow_store()


@app.route("/orderflow/summary")
def summary():
    """Live order flow summary for strategy. Low latency when fed by POST /orderflow/push."""
    s = _store().get_summary()
    age = time.time() - s.last_updated_ts
    return jsonify({
        "session_delta": s.session_delta,
        "cumulative_delta": s.cumulative_delta,
        "buy_volume": s.buy_volume,
        "sell_volume": s.sell_volume,
        "imbalance_ratio": s.imbalance_ratio,
        "last_price": s.last_price,
        "last_updated_ts": s.last_updated_ts,
        "age_seconds": round(age, 2),
        "source": s.source,
        "trade_count": s.trade_count,
        "stale": age > ORDERFLOW_TTL_SEC * 2,
    })


@app.route("/orderflow/push", methods=["POST"])
def push():
    """
    Push a trade (from your real-time feed for zero delay).
    Body: {"price": float, "size": int, "side": "buy"|"sell"}
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        price = float(data.get("price", 0))
        size = int(data.get("size", 1))
        side = str(data.get("side", "buy")).strip().lower()
        if side not in ("buy", "sell", "b", "s"):
            side = "buy"
        if size < 1 or price <= 0:
            return jsonify({"error": "invalid price or size"}), 400
        _store().push_trade(price=price, size=size, side=side)
        return jsonify({"ok": True, "session_delta": _store().get_summary().session_delta})
    except Exception as e:
        logger.warning("Orderflow push error: %s", e)
        return jsonify({"error": str(e)}), 400


@app.route("/orderflow/health")
def health():
    s = _store().get_summary()
    return jsonify({
        "status": "ok",
        "service": "mnq-orderflow-api",
        "trade_count": s.trade_count,
        "source": s.source,
    })


# ----- Optional: simulated delta from price/candle (delayed; for testing) -----
_sim_thread: threading.Thread | None = None
_sim_stop = threading.Event()


def _run_simulated_feed():
    """Background: update order flow from last 1m candle (close vs open) as proxy for delta. Has delay."""
    try:
        from api import price_server
        price_server._init_realtime_client()
    except Exception:
        price_server = None
    store = _store()
    while not _sim_stop.is_set():
        try:
            price = None
            if price_server and getattr(price_server, "_REALTIME_CLIENT", None):
                client = price_server._REALTIME_CLIENT
                price = getattr(client, "get_last_price", lambda: None)()
            if price is None:
                try:
                    from api.price_server import _fetch_current_price
                    price = _fetch_current_price()
                except Exception:
                    pass
            if price is not None:
                try:
                    from api import price_server
                    df = getattr(price_server, "_fetch_1m_candles", lambda n: None)(5)
                    if df is not None and not df.empty and len(df) >= 2:
                        row = df.iloc[-1]
                        close = float(row["close"])
                        open_ = float(row["open"])
                        vol = int(row.get("volume", 100))
                        if close > open_:
                            store.set_delta_proxy(vol, vol, 0, close, source="simulated")
                        elif close < open_:
                            store.set_delta_proxy(-vol, 0, vol, close, source="simulated")
                        else:
                            store.set_delta_proxy(0, vol // 2, vol // 2, close, source="simulated")
                    else:
                        store.set_delta_proxy(0, 0, 0, price, source="simulated")
                except Exception:
                    store.set_delta_proxy(0, 0, 0, price, source="simulated")
        except Exception as e:
            logger.debug("Orderflow sim feed: %s", e)
        _sim_stop.wait(timeout=5.0)


def start_simulated_feed():
    """Start background thread that updates order flow from candle proxy (delayed)."""
    global _sim_thread
    if _sim_thread and _sim_thread.is_alive():
        return
    _sim_stop.clear()
    _sim_thread = threading.Thread(target=_run_simulated_feed, daemon=True)
    _sim_thread.start()
    logger.info("Order flow simulated feed started (candle-based, no API key). Same free data as bot.")


def _start_tradovate_bridge_if_requested():
    """Start real order flow from Tradovate tick stream if env is set and credentials present."""
    if os.getenv("MNQ_ORDERFLOW_FROM_TRADOVATE", "").lower() not in ("1", "true", "yes"):
        return
    try:
        from config import (
            TRADOVATE_NAME,
            TRADOVATE_PASSWORD,
            TRADOVATE_APP_ID,
            TRADOVATE_APP_VERSION,
            TRADOVATE_CID,
            TRADOVATE_SEC,
            TRADOVATE_DEMO,
            TRADOVATE_MD_SYMBOL,
        )
        if not (TRADOVATE_NAME and TRADOVATE_PASSWORD and TRADOVATE_APP_ID and TRADOVATE_SEC):
            logger.info("MNQ_ORDERFLOW_FROM_TRADOVATE=true but Tradovate credentials not set; skipping bridge.")
            return
        from data.tradovate_realtime import get_tradovate_tokens
        _, token = get_tradovate_tokens(
            TRADOVATE_NAME, TRADOVATE_PASSWORD, TRADOVATE_APP_ID, TRADOVATE_APP_VERSION,
            TRADOVATE_CID or "0", TRADOVATE_SEC, demo=TRADOVATE_DEMO,
        )
        if not token:
            logger.warning("Tradovate auth failed; order flow bridge not started.")
            return
        port = int(os.getenv("MNQ_ORDERFLOW_PORT", "5002"))
        host = os.getenv("MNQ_ORDERFLOW_HOST", "127.0.0.1")
        push_url = f"http://{host}:{port}/orderflow/push"
        def run_bridge():
            from data.tradovate_orderflow_bridge import run_tradovate_orderflow_bridge
            run_tradovate_orderflow_bridge(
                md_access_token=token,
                symbol=TRADOVATE_MD_SYMBOL or "NQ",
                demo=TRADOVATE_DEMO,
                orderflow_push_url=push_url,
            )
        t = threading.Thread(target=run_bridge, daemon=True)
        t.start()
        logger.info("Tradovate order flow bridge started (real market ticks -> /orderflow/push)")
    except Exception as e:
        logger.warning("Could not start Tradovate order flow bridge: %s", e)


def main():
    port = int(os.getenv("MNQ_ORDERFLOW_PORT", "5002"))
    host = os.getenv("MNQ_ORDERFLOW_HOST", "127.0.0.1")
    want_polygon = bool(os.getenv("POLYGON_API_KEY", "").strip()) and os.getenv("MNQ_ORDERFLOW_FROM_POLYGON", "").lower() in ("1", "true", "yes")
    want_tradovate = os.getenv("MNQ_ORDERFLOW_FROM_TRADOVATE", "").lower() in ("1", "true", "yes")
    logger.info("Order Flow API starting on http://%s:%s", host, port)
    if want_polygon:
        _start_polygon_bridge_if_requested()
    if want_tradovate:
        _start_tradovate_bridge_if_requested()
    if not want_polygon and not want_tradovate:
        start_simulated_feed()
        logger.info("Order flow: no API key — using simulated feed from free price/candle data (same as bot).")
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
