"""
Test that equity curve reset actually clears the file and is visible to readers.
Run from repo root: python -m pytest mnq_bot/tests/test_equity_reset.py -v
Or: cd mnq_bot && python -c "import sys; sys.path.insert(0, '..'); from tests.test_equity_reset import *; test_equity_reset_flow()"
"""

import json
import sys
from pathlib import Path

# Project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_equity_reset_flow():
    """Write sample data, reset, verify file is [] and get_equity_curve returns []."""
    from config import DATA_DIR

    equity_path = DATA_DIR / "equity_curve.json"
    assert equity_path.parent == DATA_DIR, "equity path should be in config DATA_DIR"

    # 1) Write some fake data (like old curve)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fake_snapshots = [
        {"timestamp": "2025-01-01T10:00:00", "balance": 50000.0, "pnl": 0, "trade_count": 0},
        {"timestamp": "2025-01-01T11:00:00", "balance": 50100.0, "pnl": 100, "trade_count": 1},
    ]
    equity_path.write_text(json.dumps(fake_snapshots, indent=2), encoding="utf-8")
    assert equity_path.exists()
    data_before = json.loads(equity_path.read_text(encoding="utf-8"))
    assert len(data_before) == 2, "should have 2 snapshots before reset"

    # 2) Reset: overwrite in place with [] (same as /reset confirm)
    equity_path.write_text("[]", encoding="utf-8")

    # 3) Verify file content
    raw = equity_path.read_text(encoding="utf-8")
    data_after = json.loads(raw)
    assert data_after == [], "file should be [] after reset"

    # 4) Verify equity_tracker sees empty curve
    from data.equity_tracker import get_equity_curve, reset_equity_curve

    curve = get_equity_curve()
    assert curve == [], "get_equity_curve() should return [] after file write"

    # 5) Put data back and test reset_equity_curve()
    equity_path.write_text(json.dumps(fake_snapshots, indent=2), encoding="utf-8")
    assert len(get_equity_curve()) == 2
    ok = reset_equity_curve()
    assert ok, "reset_equity_curve() should return True"
    assert get_equity_curve() == [], "get_equity_curve() should be [] after reset_equity_curve()"
    assert json.loads(equity_path.read_text(encoding="utf-8")) == []

    print("OK: equity reset flow passed (file overwrite + get_equity_curve both see []).")


if __name__ == "__main__":
    test_equity_reset_flow()
