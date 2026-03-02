"""
Health/readiness endpoint for monitoring.
Run: python -m api.health   (default port 5003)
GET /health -> 200 {"status":"ok", "feed_connected": true|false}
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from flask import Flask, jsonify
except ImportError:
    raise ImportError("Install Flask: pip install flask")

app = Flask(__name__)


@app.route("/health")
def health():
    """Return 200 and status. Optional: probe feed with short timeout."""
    out = {"status": "ok"}
    try:
        from config import BROKER, USE_LIVE_FEED, PRICE_API_URL
        from data import get_feed
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        out["feed_connected"] = feed.is_connected()
    except Exception as e:
        out["feed_connected"] = False
        out["feed_error"] = str(e)
    return jsonify(out), 200


def main():
    port = int(os.getenv("MNQ_HEALTH_PORT", "5003"))
    host = os.getenv("MNQ_HEALTH_HOST", "0.0.0.0")
    app.run(host=host, port=port, use_reloader=False)


if __name__ == "__main__":
    main()
    sys.exit(0)
