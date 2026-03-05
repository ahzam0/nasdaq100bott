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


@app.route("/orderflow/realtime")
def realtime_flow():
    """Full real-time order flow from actual trade data (Alpaca/Finnhub)."""
    try:
        from data.orderflow_engine import compute_realtime_flow
        flow = compute_realtime_flow()
        if flow is None:
            return jsonify({"error": "No real-time data available", "is_real": False}), 200
        return jsonify({
            "is_real": flow.is_real,
            "source": flow.source,
            "data_age_seconds": round(flow.data_age_seconds, 2),
            "trade_count": flow.trade_count,
            "volume_delta": flow.volume_delta,
            "cumulative_delta": flow.cumulative_delta,
            "buy_volume": flow.buy_volume,
            "sell_volume": flow.sell_volume,
            "imbalance_ratio": round(flow.imbalance_ratio, 4),
            "vwap": round(flow.vwap, 2),
            "price_vs_vwap": round(flow.price_vs_vwap, 2),
            "tape_speed": round(flow.tape_speed, 2),
            "cvd_slope": round(flow.cvd_slope, 2),
            "delta_divergence": flow.delta_divergence,
            "divergence_type": flow.divergence_type,
            "absorption_detected": flow.absorption_detected,
            "absorption_level": flow.absorption_level,
            "absorption_side": flow.absorption_side,
            "large_order_bias": flow.large_order_bias,
            "large_orders_count": len(flow.large_orders),
            "poc_price": round(flow.poc_price, 2),
        })
    except Exception as e:
        logger.warning("Realtime flow error: %s", e)
        return jsonify({"error": str(e), "is_real": False}), 500


@app.route("/orderflow/large_trades")
def large_trades():
    """Recent large (institutional) trades."""
    try:
        from data.orderflow_engine import compute_realtime_flow
        flow = compute_realtime_flow()
        if flow is None or not flow.large_orders:
            return jsonify({"trades": [], "source": "none"})
        trades = [{
            "time": lo.timestamp,
            "price": round(lo.price_nq, 2),
            "size": lo.size,
            "side": lo.side,
            "multiple": round(lo.multiple_of_avg, 1),
        } for lo in flow.large_orders[-10:]]
        return jsonify({"trades": trades, "bias": flow.large_order_bias, "source": flow.source})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/orderflow/health")
def health():
    s = _store().get_summary()
    # Check real-time collector status
    rt_source = "none"
    rt_connected = False
    try:
        from data.realtime_collector import get_collector_manager
        mgr = get_collector_manager()
        rt_source = mgr.source
        rt_connected = mgr.connected
    except Exception:
        pass
    return jsonify({
        "status": "ok",
        "service": "mnq-orderflow-api",
        "trade_count": s.trade_count,
        "source": s.source,
        "realtime_source": rt_source,
        "realtime_connected": rt_connected,
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


def _start_realtime_collectors():
    """Start Alpaca/Finnhub real-time collectors if API keys are configured."""
    try:
        from data.realtime_collector import get_collector_manager
        from config import (
            ALPACA_DATA_API_KEY, ALPACA_DATA_SECRET_KEY, FINNHUB_API_KEY,
        )
        mgr = get_collector_manager()
        desc = mgr.start(
            alpaca_key=ALPACA_DATA_API_KEY,
            alpaca_secret=ALPACA_DATA_SECRET_KEY,
            finnhub_key=FINNHUB_API_KEY,
        )
        logger.info("Real-time collectors: %s", desc)
    except ImportError as e:
        logger.debug("Real-time collector config not available: %s", e)
    except Exception as e:
        logger.warning("Could not start real-time collectors: %s", e)


def main():
    port = int(os.getenv("MNQ_ORDERFLOW_PORT", "5002"))
    host = os.getenv("MNQ_ORDERFLOW_HOST", "127.0.0.1")
    want_polygon = bool(os.getenv("POLYGON_API_KEY", "").strip()) and os.getenv("MNQ_ORDERFLOW_FROM_POLYGON", "").lower() in ("1", "true", "yes")
    want_tradovate = os.getenv("MNQ_ORDERFLOW_FROM_TRADOVATE", "").lower() in ("1", "true", "yes")
    logger.info("Order Flow API starting on http://%s:%s", host, port)

    # Start real-time collectors (Alpaca/Finnhub)
    _start_realtime_collectors()

    if want_polygon:
        _start_polygon_bridge_if_requested()
    if want_tradovate:
        _start_tradovate_bridge_if_requested()
    if not want_polygon and not want_tradovate:
        from data.realtime_collector import get_collector_manager
        if not get_collector_manager().connected:
            start_simulated_feed()
            logger.info("Order flow: no API key — using simulated feed from free price/candle data (same as bot).")
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
