#!/usr/bin/env python3
"""
Check which price feed the app uses and whether it's delay-free.
Run from repo root: python scripts/check_price_feed.py
Best run when market is open (US session).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    from config import BROKER, USE_LIVE_FEED, PRICE_API_URL, USE_YAHOO_WS_REALTIME
    from data import get_feed

    feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
    feed_type = type(feed).__name__

    # Classify delay
    delay_free = feed_type in ("YahooWSFeed", "TradovateRealtimeFeed")
    if delay_free:
        delay_note = "minimal delay (WebSocket / real-time)"
    elif feed_type == "LocalAPIFeed":
        delay_note = "depends on Price API cache (usually minimal)"
    else:
        delay_note = "Yahoo REST = delayed (15–20 min typical)"

    print("=== Price feed check (same as bot) ===")
    print(f"Feed type:    {feed_type}")
    print(f"Delay:        {delay_note}")
    print(f"Connected:    {feed.is_connected()}")

    # Fetch current price and time it
    t0 = time.perf_counter()
    try:
        price = feed.get_current_price()
        elapsed_ms = (time.perf_counter() - t0) * 1000
    except Exception as e:
        print(f"Price fetch:  ERROR – {e}")
        return 1
    if price is None:
        print("Price fetch:  No price (market closed or feed not updating)")
        return 0
    print(f"Current price: {price:,.2f}  (fetch took {elapsed_ms:.0f} ms)")

    # Quick 1m candles check (what scan uses)
    try:
        df_1m = feed.get_1m_candles(5)
        if df_1m is not None and not df_1m.empty:
            last_ts = df_1m.index[-1]
            print(f"Last 1m bar:  {last_ts} (candles OK for scan)")
        else:
            print("Last 1m bar:  No data")
    except Exception as e:
        print(f"1m candles:   ERROR – {e}")

    # One-line summary: delay-free yes/no
    actually_delay_free = False
    if feed_type == "YahooWSFeed":
        ws = getattr(feed, "_ws", None)
        actually_delay_free = bool(ws and ws.is_connected())
    elif feed_type == "TradovateRealtimeFeed":
        actually_delay_free = feed.is_connected()
    elif feed_type == "LocalAPIFeed":
        actually_delay_free = feed.is_connected()

    print()
    print(f"Delay-free:   {'yes' if actually_delay_free else 'no'}")
    if delay_free and not actually_delay_free:
        print("(Feed supports delay-free but not active now – e.g. market closed; using REST fallback.)")
    elif delay_free:
        print("OK – App is using a low-delay feed (WebSocket/realtime).")
    else:
        print("NOTE – App is using a delayed feed. For live trading with minimal delay, enable:")
        print("  Yahoo WebSocket: MNQ_YAHOO_WS_REALTIME=true (default)")
        print("  Or Tradovate:    MNQ_TRADOVATE_REALTIME=true + credentials")
    return 0


if __name__ == "__main__":
    sys.exit(main())
