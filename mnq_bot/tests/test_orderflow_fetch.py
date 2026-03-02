"""
Verify the app properly fetches live order flow from our API.
Requires: Order Flow API running (python -m api.orderflow_server) on port 5002.
Run: python tests/test_orderflow_fetch.py
  or: python -m unittest tests.test_orderflow_fetch -v
"""
from __future__ import annotations

import sys
import json
import urllib.request
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestOrderflowFetch(unittest.TestCase):
    """Requires order flow server on http://127.0.0.1:5002."""

    def test_summary_response_has_required_keys(self):
        """GET /orderflow/summary must return keys the checklist uses."""
        try:
            req = urllib.request.Request("http://127.0.0.1:5002/orderflow/summary")
            with urllib.request.urlopen(req, timeout=2) as r:
                summary = json.loads(r.read().decode())
        except OSError as e:
            self.skipTest("Order flow API not running: %s. Start: python -m api.orderflow_server" % e)
        self.assertIn("age_seconds", summary)
        self.assertIn("imbalance_ratio", summary)
        self.assertIsInstance(summary.get("imbalance_ratio"), (int, float))
        self.assertIsInstance(summary.get("age_seconds"), (int, float))

    def test_main_fetch_returns_same_shape(self):
        """main._fetch_orderflow_summary returns dict with age_seconds and imbalance_ratio."""
        import main as main_mod
        summary = main_mod._fetch_orderflow_summary(timeout_sec=2)
        if summary is None:
            self.skipTest("Order flow server not reachable at ORDERFLOW_API_URL")
        self.assertIn("age_seconds", summary)
        self.assertIn("imbalance_ratio", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
