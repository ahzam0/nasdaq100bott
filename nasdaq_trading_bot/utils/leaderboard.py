"""Global leaderboard of top N parameter sets across all runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
LEADERBOARD_PATH = ROOT / "output" / "leaderboard.json"


def _serialize_params(p: np.ndarray) -> list:
    return np.asarray(p).ravel().tolist()


class Leaderboard:
    """Maintain top N (params, score, metrics_snapshot) entries."""

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.entries: List[dict] = []

    def update(self, params: np.ndarray, metrics: Any, score: float, strategy_name: str = "") -> None:
        entry = {
            "params": _serialize_params(params),
            "score": score,
            "strategy": strategy_name,
            "sharpe": getattr(metrics, "sharpe_ratio", None),
            "cagr_pct": getattr(metrics, "cagr_pct", None),
            "max_dd_pct": getattr(metrics, "max_drawdown_pct", None),
        }
        self.entries.append(entry)
        self.entries.sort(key=lambda x: x["score"], reverse=True)
        self.entries = self.entries[: self.max_size]

    def save(self, path: Optional[Path] = None) -> None:
        path = path or LEADERBOARD_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2)

    def load(self, path: Optional[Path] = None) -> None:
        path = path or LEADERBOARD_PATH
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            self.entries = json.load(f)
        self.entries = self.entries[: self.max_size]

    def best_params(self) -> Optional[np.ndarray]:
        if not self.entries:
            return None
        return np.array(self.entries[0]["params"], dtype=float)
