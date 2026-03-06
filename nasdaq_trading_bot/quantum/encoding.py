"""
Encode NASDAQ features as quantum state vectors.
Angle encoding, amplitude encoding, entanglement for correlated pairs.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Correlated NASDAQ pairs for entanglement
NASDAQ_ENTANGLED_PAIRS = [
    ("AAPL", "MSFT"),
    ("NVDA", "AMD"),
    ("GOOGL", "META"),
    ("QQQ", "TQQQ"),
]


def _normalize(x: np.ndarray, low: float = 0.0, high: float = 1.0) -> np.ndarray:
    """Map values to [low, high] then to [0, 2*pi] for rotation angles."""
    x = np.asarray(x, dtype=float)
    x = np.nan_to_num(x, nan=0.0, posinf=1.0, neginf=0.0)
    if x.size == 0:
        return x
    mn, mx = x.min(), x.max()
    if mx - mn > 1e-12:
        x = (x - mn) / (mx - mn)
    x = x * (high - low) + low
    return x * 2 * np.pi


def encode_features_angle(
    features: np.ndarray,
    n_qubits: Optional[int] = None,
    low: float = 0.0,
    high: float = 1.0,
) -> np.ndarray:
    """
    Angle encoding: each feature -> rotation angle on Bloch sphere.
    Returns array of angles in [0, 2*pi], length = min(n_qubits, len(features)).
    """
    features = np.asarray(features).ravel()
    if n_qubits is not None:
        if len(features) > n_qubits:
            features = features[:n_qubits]
        elif len(features) < n_qubits:
            features = np.resize(features, n_qubits)
    angles = _normalize(features, low, high)
    return angles


def encode_amplitude(features: np.ndarray, n_qubits: Optional[int] = None) -> np.ndarray:
    """
    Amplitude encoding: normalize feature vector to unit length for superposition.
    Returns normalized vector (length 2^n_qubits or len(features)).
    """
    features = np.asarray(features).ravel().astype(float)
    features = np.nan_to_num(features, nan=0.0)
    n = len(features)
    if n_qubits is not None:
        dim = 2 ** min(n_qubits, 10)
        if n < dim:
            features = np.resize(features, dim)
        else:
            features = features[:dim]
    norm = np.linalg.norm(features)
    if norm < 1e-12:
        return features
    return features / norm


def encode_entangled_pairs(
    feature_matrix: np.ndarray,
    pair_indices: list[tuple[int, int]],
) -> np.ndarray:
    """
    Encode correlated pairs (e.g. AAPL index, MSFT index) as entangled qubit pairs.
    Returns combined angle vector: for each pair (i,j), store [angle_i, angle_j, correlation_phase].
    """
    out = []
    for i, j in pair_indices:
        if i >= len(feature_matrix) or j >= len(feature_matrix):
            continue
        a, b = feature_matrix[i], feature_matrix[j]
        out.extend([a, b, (a - b) * 0.5])
    return np.array(out, dtype=float) if out else np.array([0.0])


def state_vector_from_angles(angles: np.ndarray) -> np.ndarray:
    """Build a 2^n qubit state vector from rotation angles (RY on each qubit)."""
    n = min(len(angles), 12)
    angles = angles[:n]
    # Single qubit RY(θ)|0> = cos(θ/2)|0> + sin(θ/2)|1>
    state = np.array([1.0 + 0.0j])
    for th in angles:
        c, s = np.cos(th / 2), np.sin(th / 2)
        state = np.kron(state, np.array([c, s]))
    return state
