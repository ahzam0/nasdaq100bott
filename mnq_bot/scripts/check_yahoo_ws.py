#!/usr/bin/env python3
"""
Verify Yahoo WebSocket is working: create client, wait for a price, print result.
Run from repo root: python scripts/check_yahoo_ws.py
Market hours (US) give best chance of receiving messages.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main():
    has_ws = False
    try:
        import yfinance as yf
        has_ws = hasattr(yf, "WebSocket")
    except ImportError:
        print("yfinance not installed. pip install yfinance")
        return 1
    if not has_ws:
        print("Your yfinance version has no WebSocket. Upgrade: pip install --upgrade yfinance")
        return 1

    print("Creating Yahoo WebSocket client (QQQ -> NQ equivalent)...")
    from data.yahoo_ws_realtime import create_yahoo_ws_client, DEFAULT_QQQ_TO_NQ_RATIO
    client = create_yahoo_ws_client(qqq_to_nq_ratio=DEFAULT_QQQ_TO_NQ_RATIO)
    # Wait up to 12s for first price (start() already waited 10s)
    for _ in range(8):
        time.sleep(0.25)
        qqq = client.get_last_price()
        if qqq is not None:
            nq = client.get_nq_equivalent_price()
            print(f"OK – Yahoo WebSocket is working. QQQ={qqq:.2f} -> NQ equiv={nq:.2f}")
            return 0
    print("No price received in 12s. Possible causes: market closed, Yahoo WS format changed, or network.")
    print("Bot will fall back to Yahoo REST (delayed) for current price.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
