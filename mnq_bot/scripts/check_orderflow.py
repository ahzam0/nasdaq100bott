#!/usr/bin/env python3
"""
Check if order flow data is being received (same as bot uses).
Run from repo root: python scripts/check_orderflow.py
Requires: Order Flow API running (python -m api.orderflow_server) if ORDERFLOW_API_URL is set.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    from config import ORDERFLOW_API_URL, USE_ORDERFLOW, ORDERFLOW_STALE_SEC

    print("=== Order flow check ===")
    print(f"ORDERFLOW_API_URL:  {ORDERFLOW_API_URL or '(not set)'}")
    print(f"USE_ORDERFLOW:      {USE_ORDERFLOW}")

    # Bot no longer fetches order flow in run_scan; script still can check API if present
    try:
        from main import _fetch_orderflow_summary
    except (ImportError, AttributeError):
        print()
        print("Order flow fetch not available in bot (removed from strategy).")
        print("ORDERFLOW_API_URL is still used by config; bot does not call it.")
        return 0

    if not ORDERFLOW_API_URL or not ORDERFLOW_API_URL.strip():
        print()
        print("Order flow:  not configured (ORDERFLOW_API_URL empty).")
        print("To enable: set MNQ_ORDERFLOW_API_URL (e.g. http://127.0.0.1:5002) and run: python -m api.orderflow_server")
        return 0

    summary = _fetch_orderflow_summary(timeout_sec=3)
    if summary is None:
        print()
        print("Order flow data:  NO (fetch failed or timeout)")
        print("Ensure order flow server is running: python -m api.orderflow_server")
        print("And that nothing is blocking the URL (firewall, wrong host/port).")
        return 1

    age = summary.get("age_seconds", None)
    imb = summary.get("imbalance_ratio", None)
    stale = age is not None and age > ORDERFLOW_STALE_SEC
    print()
    print("Order flow data:  YES")
    print(f"  age_seconds:     {age if age is not None else 'n/a'}")
    print(f"  imbalance_ratio: {imb if imb is not None else 'n/a'}")
    print(f"  stale (> {ORDERFLOW_STALE_SEC}s):  {'yes' if stale else 'no'}")
    if stale:
        print("  (Strategy may skip order flow check when stale; entries still allowed.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
