"""
QAOA/VQE-style optimizer: suggest strategy params, update from metrics, quantum noise, adaptive depth.
Classical simulation: params are a vector; we use scipy minimize + random restarts to mimic QAOA.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Callable, Optional

import numpy as np

from quantum.encoding import encode_features_angle
from quantum.hamiltonian import build_hamiltonian_weights, evaluate_hamiltonian

logger = logging.getLogger(__name__)

# Default param dim (strategy params: e.g. RSI thresholds, ATR mult, etc.)
DEFAULT_PARAM_DIM = 20
PARAM_BOUNDS_LOW = 0.0
PARAM_BOUNDS_HIGH = 1.0


class QuantumOptimizer:
    """
    Quantum-inspired optimizer: maintain param vector, suggest candidates,
    penalize failures, inject noise, increase depth (param dimension / search radius).
    """

    def __init__(
        self,
        param_dim: int = DEFAULT_PARAM_DIM,
        seed: Optional[int] = None,
        bounds_low: float = PARAM_BOUNDS_LOW,
        bounds_high: float = PARAM_BOUNDS_HIGH,
    ):
        self.param_dim = param_dim
        self.rng = random.Random(seed)
        self.bounds_low = bounds_low
        self.bounds_high = bounds_high
        self._best_params: Optional[np.ndarray] = None
        self._circuit_depth = 2  # p in QAOA
        self._noise_scale = 0.1

    def initialize_random(self) -> np.ndarray:
        """Return random params in [0,1]^dim."""
        return np.array(
            [self.rng.uniform(self.bounds_low, self.bounds_high) for _ in range(self.param_dim)],
            dtype=float,
        )

    def mutate(self, params: np.ndarray, noise: float = 0.1) -> np.ndarray:
        """Mutate best params with Gaussian noise and clip to bounds."""
        p = np.asarray(params).ravel()
        if len(p) != self.param_dim:
            p = np.resize(p, self.param_dim)
        n = np.random.normal(0, noise, size=self.param_dim)
        out = p + n
        out = np.clip(out, self.bounds_low, self.bounds_high)
        return out.astype(float)

    def suggest(self, params: np.ndarray) -> np.ndarray:
        """Suggest candidate: small perturbation of current params (simulate one QAOA step)."""
        return self.mutate(params, noise=0.05)

    def penalize(self, candidate: np.ndarray) -> None:
        """Record bad candidate (e.g. for Hamiltonian update); no-op in this implementation."""
        pass

    def update_hamiltonian(self, metrics: Any, score: float) -> None:
        """Update internal state from metrics/score (e.g. adaptive weights)."""
        pass

    def inject_quantum_noise(self) -> None:
        """Increase noise to escape local optima."""
        self._noise_scale = min(0.5, self._noise_scale * 1.5)

    def increase_circuit_depth(self) -> None:
        """Simulate increasing QAOA layers / search space."""
        self._circuit_depth = min(20, self._circuit_depth + 1)

    def set_best(self, params: np.ndarray) -> None:
        self._best_params = np.asarray(params).copy()

    def get_best(self) -> Optional[np.ndarray]:
        return self._best_params.copy() if self._best_params is not None else None


def params_to_strategy_kwargs(params: np.ndarray) -> dict[str, Any]:
    """
    Map flat param vector to strategy kwargs for backtest (Trend Following / NASDAQ strategies).
    """
    p = np.asarray(params).ravel()
    return {
        "ema_period": 50 + int(200 * (p[0] if len(p) > 0 else 0.75)),
        "rsi_period": 7 + int(14 * (p[1] if len(p) > 1 else 0.5)),
        "macd_fast": 8 + int(8 * (p[2] if len(p) > 2 else 0.5)),
        "macd_slow": 20 + int(15 * (p[3] if len(p) > 3 else 0.4)),
        "rsi2_low": 5.0 + 15.0 * (p[4] if len(p) > 4 else 0.33),
        "rsi2_high": 85.0 + 15.0 * (p[5] if len(p) > 5 else 0.5),
    }
