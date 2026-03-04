"""
Local Price API for MNQ bot – single place to fetch price/candles.
Serves the freshest data from the configured source (Yahoo). Swap backend here for real-time when available.
Run: python -m api.price_server   (default port 5001)
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache to avoid delay from repeated Yahoo calls – our API responds from cache when valid
_PRICE_CACHE: dict = {}  # { "price", "timestamp", "ts" }
_CANDLES_1M_CACHE: dict = {}
_CANDLES_15M_CACHE: dict = {}
PRICE_TTL_SEC = float(os.getenv("MNQ_PRICE_CACHE_TTL", "5"))   # current price cache
CANDLES_TTL_SEC = float(os.getenv("MNQ_CANDLES_CACHE_TTL", "30"))

# Optional: delay-free Tradovate WebSocket client (when credentials set)
_REALTIME_CLIENT = None


def _init_realtime_client():
    global _REALTIME_CLIENT
    if _REALTIME_CLIENT is not None:
        return
    # 1) Free Yahoo WebSocket (minimal delay, no API key)
    try:
        from config import get_use_yahoo_ws_realtime, YAHOO_WS_QQQ_TO_NQ_RATIO
        if get_use_yahoo_ws_realtime():
            from data.yahoo_ws_realtime import get_or_create_yahoo_ws_client
            client = get_or_create_yahoo_ws_client(qqq_to_nq_ratio=YAHOO_WS_QQQ_TO_NQ_RATIO)
            if client:
                _REALTIME_CLIENT = client
                logger.info("Price API: Yahoo WebSocket backend active (free, minimal delay)")
                return
    except Exception as e:
        logger.debug("Yahoo WS init skipped: %s", e)
    # 2) Tradovate (requires account)
    use_realtime = os.getenv("MNQ_TRADOVATE_REALTIME", "").lower() in ("1", "true", "yes")
    if not use_realtime:
        return
    try:
        from data.tradovate_realtime import create_tradovate_md_client
        from config import (
            TRADOVATE_NAME, TRADOVATE_PASSWORD, TRADOVATE_APP_ID, TRADOVATE_APP_VERSION,
            TRADOVATE_CID, TRADOVATE_SEC, TRADOVATE_DEMO, TRADOVATE_MD_SYMBOL, TRADOVATE_ACCESS_TOKEN,
        )
        if not (TRADOVATE_ACCESS_TOKEN or (TRADOVATE_NAME and TRADOVATE_PASSWORD and TRADOVATE_APP_ID and TRADOVATE_SEC)):
            return
        _REALTIME_CLIENT = create_tradovate_md_client(
            name=TRADOVATE_NAME, password=TRADOVATE_PASSWORD,
            app_id=TRADOVATE_APP_ID, app_version=TRADOVATE_APP_VERSION,
            cid=TRADOVATE_CID, sec=TRADOVATE_SEC,
            md_access_token=TRADOVATE_ACCESS_TOKEN or "",
            symbol=TRADOVATE_MD_SYMBOL, demo=TRADOVATE_DEMO,
        )
        if _REALTIME_CLIENT:
            logger.info("Price API: Tradovate real-time backend active (delay-free)")
    except Exception as e:
        logger.debug("Tradovate realtime init skipped: %s", e)

try:
    from flask import Flask, jsonify, request
except ImportError:
    raise ImportError("Install Flask: pip install flask")

# Add project root
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

app = Flask(__name__)


def _fetch_current_price() -> float | None:
    """Fetch latest price from Yahoo (NQ=F). Replace this with WebSocket/broker for real-time."""
    try:
        import yfinance as yf
        from backtest.live_data import YF_SYMBOLS
        for symbol in YF_SYMBOLS:
            try:
                t = yf.Ticker(symbol)
                price = getattr(t.fast_info, "lastPrice", None)
                if price is not None:
                    p = float(price)
                    if p == p:  # not nan
                        return p
                h = t.history(period="1d", interval="1m", prepost=True)
                if h is not None and not h.empty and "Close" in h.columns:
                    return float(h["Close"].iloc[-1])
            except Exception:
                continue
    except Exception as e:
        logger.warning("Price fetch failed: %s", e)
    return None


def _fetch_1m_candles(count: int = 100):
    try:
        from backtest.live_data import fetch_yfinance_1m, YF_SYMBOLS
        for symbol in YF_SYMBOLS:
            df = fetch_yfinance_1m(symbol=symbol, period="7d")
            if df is not None and not df.empty and len(df) >= 2:
                return df.tail(count)
    except Exception as e:
        logger.warning("1m candles fetch failed: %s", e)
    return None


def _fetch_15m_candles(count: int = 50):
    try:
        from backtest.live_data import fetch_yfinance_15m, YF_SYMBOLS
        for symbol in YF_SYMBOLS:
            df = fetch_yfinance_15m(symbol=symbol, period="7d")
            if df is not None and not df.empty and len(df) >= 2:
                return df.tail(count)
    except Exception as e:
        logger.warning("15m candles fetch failed: %s", e)
    return None


def _df_to_candles(df):
    if df is None or df.empty:
        return []
    rows = []
    for ts, row in df.iterrows():
        t = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        rows.append({
            "timestamp": t,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row.get("volume", 0)),
        })
    return rows


@app.route("/price")
def price():
    """Current NQ price. Uses Tradovate real-time when configured (delay-free); else Yahoo (cached)."""
    _init_realtime_client()
    # Prefer delay-free real-time price (Alpaca QQQ->NQ or Tradovate NQ)
    if _REALTIME_CLIENT:
        fn = getattr(_REALTIME_CLIENT, "get_nq_equivalent_price", None)
        p_realtime = fn() if callable(fn) else _REALTIME_CLIENT.get_last_price()
        if p_realtime is not None:
            return jsonify({
                "symbol": "NQ",
                "price": p_realtime,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cached": False,
                "realtime": True,
            })
    now = time.time()
    c = _PRICE_CACHE
    if c and (now - c.get("ts", 0)) <= PRICE_TTL_SEC and c.get("price") is not None:
        return jsonify({
            "symbol": c.get("symbol", "NQ=F"),
            "price": c["price"],
            "timestamp": c.get("timestamp"),
            "cached": True,
        })
    p = _fetch_current_price()
    if p is not None:
        _PRICE_CACHE["price"] = p
        _PRICE_CACHE["ts"] = now
        _PRICE_CACHE["timestamp"] = datetime.now(timezone.utc).isoformat()
        _PRICE_CACHE["symbol"] = "NQ=F"
        return jsonify({
            "symbol": "NQ=F",
            "price": p,
            "timestamp": _PRICE_CACHE["timestamp"],
            "cached": False,
        })
    if c and c.get("price") is not None:
        return jsonify({
            "symbol": c.get("symbol", "NQ=F"),
            "price": c["price"],
            "timestamp": c.get("timestamp"),
            "cached": True,
            "stale": True,
        })
    return jsonify({"error": "no price available"}), 503


@app.route("/candles/1m")
def candles_1m():
    count = min(int(request.args.get("count", 100)), 500)
    now = time.time()
    c = _CANDLES_1M_CACHE
    if c and (now - c.get("ts", 0)) <= CANDLES_TTL_SEC and c.get("data"):
        return jsonify({"candles": c["data"], "cached": True})
    df = _fetch_1m_candles(count)
    if df is not None and not df.empty:
        data = _df_to_candles(df)
        _CANDLES_1M_CACHE["data"] = data
        _CANDLES_1M_CACHE["ts"] = now
        return jsonify({"candles": data, "cached": False})
    if c and c.get("data"):
        return jsonify({"candles": c["data"], "cached": True, "stale": True})
    return jsonify({"error": "no 1m candles"}), 503


@app.route("/candles/15m")
def candles_15m():
    count = min(int(request.args.get("count", 50)), 200)
    now = time.time()
    c = _CANDLES_15M_CACHE
    if c and (now - c.get("ts", 0)) <= CANDLES_TTL_SEC and c.get("data"):
        return jsonify({"candles": c["data"], "cached": True})
    df = _fetch_15m_candles(count)
    if df is not None and not df.empty:
        data = _df_to_candles(df)
        _CANDLES_15M_CACHE["data"] = data
        _CANDLES_15M_CACHE["ts"] = now
        return jsonify({"candles": data, "cached": False})
    if c and c.get("data"):
        return jsonify({"candles": c["data"], "cached": True, "stale": True})
    return jsonify({"error": "no 15m candles"}), 503


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "mnq-price-api"})


def main():
    port = int(os.getenv("MNQ_PRICE_API_PORT", "5001"))
    host = os.getenv("MNQ_PRICE_API_HOST", "127.0.0.1")
    logger.info("Price API starting on http://%s:%s (price cache TTL=%ss)", host, port, PRICE_TTL_SEC)
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
