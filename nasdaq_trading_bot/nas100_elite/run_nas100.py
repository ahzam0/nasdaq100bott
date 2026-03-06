"""
Run NAS100 Elite optimizer — hit-and-trial until all 5 targets met.
Usage: python -m nas100_elite.run_nas100
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nas100_elite.optimizer_nas100 import main

if __name__ == "__main__":
    sys.exit(main())
