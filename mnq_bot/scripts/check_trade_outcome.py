"""
Fetch NQ 1m data and determine what happened to the LONG trade:
  Entry 24,871 @ 09:51 AM EST, Stop 24,715.50, trailed to 24,871 (breakeven), TP1 25,182, TP2 25,415.25
Run: python scripts/check_trade_outcome.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from zoneinfo import ZoneInfo
import pandas as pd

EST = ZoneInfo("America/New_York")

# Trade details from the alert
ENTRY = 24871.0
STOP_ORIGINAL = 24715.5
TP1 = 25182.0
TP2 = 25415.25
TRAIL_STOP = 24871.0  # breakeven after +1R

def main():
    try:
        from backtest.live_data import fetch_yfinance_1m, EST
    except Exception as e:
        print(f"Import error: {e}")
        return

    print("Fetching NQ=F 1m data (last 7 days)...")
    df = fetch_yfinance_1m(symbol="NQ=F", period="7d")
    if df is None or df.empty:
        print("No data. Check internet / yfinance.")
        return

    if df.index.tzinfo is None:
        df.index = df.index.tz_localize(EST, ambiguous="infer")
    else:
        df.index = df.index.tz_convert(EST)

    # Session 7–11 EST
    df = df.between_time("07:00", "11:59")
    if df.empty:
        print("No session data.")
        return

    # Find the bar at 09:51 EST (entry bar) on the latest day we have
    df = df.sort_index()
    entry_time = df.index[df.index >= pd.Timestamp("09:51", tz=EST)]
    if len(entry_time) == 0:
        # Use last available day's 09:51
        days = df.index.normalize().unique()
        if len(days) == 0:
            print("No data after 09:51.")
            return
        target_date = days[-1]
        entry_time = df.index[(df.index.normalize() == target_date) & (df.index.hour == 9) & (df.index.minute >= 51)]
    if len(entry_time) == 0:
        entry_time = df.index[df.index >= df.index[-1] - pd.Timedelta(hours=2)]
    if len(entry_time) == 0:
        print("Could not find entry bar (09:51 EST).")
        print("Sample index:", df.index[:5].tolist(), "...", df.index[-5:].tolist())
        return

    start_idx = df.index.get_loc(entry_time[0])
    if isinstance(start_idx, slice):
        start_idx = start_idx.start
    bars_after_entry = df.iloc[start_idx:]

    print(f"\nTrade: LONG @ {ENTRY:,.2f} | Stop (trailed) {TRAIL_STOP:,.2f} | TP2 {TP2:,.2f}")
    print(f"Bars from entry: {len(bars_after_entry)} (from {bars_after_entry.index[0]})")
    print()

    # Simulate: after entry, which level is hit first (bar by bar)?
    for i, (ts, row) in enumerate(bars_after_entry.iterrows()):
        low, high = float(row["low"]), float(row["high"])
        # After trail, stop = 24871. So check: did we hit trail stop (low <= 24871) or TP2 (high >= 25415.25)?
        if low <= TRAIL_STOP:
            print(f"  [{ts}] LOW {low:,.2f} -> STOP HIT at breakeven {TRAIL_STOP:,.2f}")
            print("\n>>> OUTCOME: Stopped out at breakeven (24,871). P&L ~ $0/contract.")
            return
        if high >= TP2:
            print(f"  [{ts}] HIGH {high:,.2f} -> TARGET 2 HIT {TP2:,.2f}")
            print("\n>>> OUTCOME: TP2 hit. Full target (+544 pts / +$1,088 per contract if 100% runner).")
            return
        if high >= TP1:
            print(f"  [{ts}] HIGH {high:,.2f} -> TP1 hit (50% could be taken at 25,182)")
        # Optional: if we want to stop at TP1 for partial
        # if high >= TP1: ...

    # Ran out of bars
    last = bars_after_entry.iloc[-1]
    last_ts = bars_after_entry.index[-1]
    last_close = float(last["close"])
    print(f"  End of data at {last_ts}. Last close {last_close:,.2f}.")
    if last_close >= TP2:
        print("\n>>> OUTCOME: Price reached TP2 by end of data.")
    elif last_close <= TRAIL_STOP:
        print("\n>>> OUTCOME: Price at or below trail stop by end of data.")
    else:
        print("\n>>> OUTCOME: No clear exit in this data window. Position may still be open or closed later.")

if __name__ == "__main__":
    main()
