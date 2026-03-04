"""
Fetch NQ=F 7d 1m from Yahoo Chart API and check what happened to the trade.
Entry 24,871 @ 09:51 EST, trail stop 24,871, TP2 25,415.25.
Run: python fetch_nq_outcome.py   (from mnq_bot/scripts)
"""
import json
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")
ENTRY = 24871.0
TRAIL_STOP = 24871.0
TP1 = 25182.0
TP2 = 25415.25

def main():
    url = "https://query1.finance.yahoo.com/v8/finance/chart/NQ=F?interval=1m&range=7d"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        print(f"Fetch error: {e}")
        return
    try:
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        quote = res["indicators"]["quote"][0]
        highs = quote["high"]
        lows = quote["low"]
        closes = quote["close"]
    except (KeyError, IndexError) as e:
        print(f"Parse error: {e}")
        return

    # Build bars: (timestamp_est, high, low, close)
    bars = []
    for i, t in enumerate(ts):
        if t is None:
            continue
        dt = datetime.fromtimestamp(t, tz=EST)
        h = highs[i] if i < len(highs) and highs[i] is not None else None
        l = lows[i] if i < len(lows) and lows[i] is not None else None
        c = closes[i] if i < len(closes) and closes[i] is not None else None
        if h is not None and l is not None:
            bars.append((dt, h, l, c))
    if not bars:
        print("No OHLC bars.")
        return

    # Find 09:51 EST on the most recent day
    bars_after_951 = []
    for dt, h, l, c in bars:
        if dt.hour == 9 and dt.minute >= 51:
            bars_after_951.append((dt, h, l, c))
        elif dt.hour > 9:
            bars_after_951.append((dt, h, l, c))
    if not bars_after_951:
        # use last 2 hours of data
        bars_after_951 = bars[-120:]
    else:
        # only same day after 09:51
        first_951 = next((b for b in bars if b[0].hour == 9 and b[0].minute >= 51), None)
        if first_951:
            start_dt = first_951[0]
            bars_after_951 = [b for b in bars if b[0] >= start_dt]

    print(f"Trade: LONG @ {ENTRY:,.0f} | Trail stop @ {TRAIL_STOP:,.0f} | TP2 @ {TP2:,.0f}")
    print(f"Bars after 09:51 EST: {len(bars_after_951)}")
    if bars_after_951:
        print(f"From {bars_after_951[0][0]} to {bars_after_951[-1][0]}\n")
    for dt, h, l, c in bars_after_951:
        if l <= TRAIL_STOP:
            print(f"  {dt} LOW {l:,.2f} -> STOP HIT (breakeven {TRAIL_STOP:,.0f})")
            print("\n>>> OUTCOME: Stopped out at breakeven. P&L ~ $0/contract.")
            return
        if h >= TP2:
            print(f"  {dt} HIGH {h:,.2f} -> TP2 HIT {TP2:,.0f}")
            print("\n>>> OUTCOME: TP2 hit. Full target (~+$1,088/contract on runner).")
            return
        if h >= TP1:
            print(f"  {dt} HIGH {h:,.2f} -> TP1 (25,182) reached")
    last = bars_after_951[-1]
    print(f"  End of data: {last[0]} close {last[2]:,.2f}")
    print("\n>>> OUTCOME: No clear exit in window. Check broker for actual fill.")

if __name__ == "__main__":
    main()
