"""
Elite Trading Signal System — Entry point.
Run hit-and-trial until all 5 metrics are met, then output daily format and tracker.
Usage: python -m elite_signal_system.run_elite   or   python elite_signal_system/run_elite.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from elite_signal_system.optimizer_loop import main as optimizer_main


if __name__ == "__main__":
    sys.exit(optimizer_main())
