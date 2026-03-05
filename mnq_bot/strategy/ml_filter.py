"""
ML signal filter for MNQ trading bot.
Lightweight weighted scoring: no sklearn/tensorflow. Learns from trade outcomes via Bayesian update.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import DATA_DIR
from strategy.setups import ReversalSetup, SetupType
from strategy.market_structure import TrendDirection

logger = logging.getLogger(__name__)

WEIGHTS_PATH = DATA_DIR / "ml_weights.json"
DEFAULT_THRESHOLD = 0.5

# Default weights for score components (sum of bonuses + base ≈ 1.0)
DEFAULT_WEIGHTS = {
    "base": 0.10,
    "trend_aligned": 0.20,
    "confidence_score": 0.15,
    "reward_risk_ge_1_5": 0.15,
    "is_retest": 0.10,
    "hour_8_10": 0.10,
    "body_ratio_gt_0_5": 0.10,
    "low_volatility": 0.10,
}

# Feature keys used in scoring (for train_from_history)
SCORING_KEYS = [
    "trend_aligned",
    "confidence_score",
    "reward_risk_ge_1_5",
    "is_retest",
    "hour_8_10",
    "body_ratio_gt_0_5",
    "low_volatility",
]


def _atr(df: pd.DataFrame, period: int = 14) -> float | None:
    """Compute ATR (Average True Range) for last bar. Returns None if insufficient data."""
    if df.empty or len(df) < period + 1:
        return None
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    tr = high - low
    prev_close = close.shift(1)
    tr = np.maximum(tr, np.abs(high - prev_close))
    tr = np.maximum(tr, np.abs(low - prev_close))
    return float(tr.iloc[-period:].mean())


def extract_features(
    setup: ReversalSetup,
    df_1m: pd.DataFrame,
    trend: TrendDirection,
    now_est: pd.Timestamp | None = None,
) -> dict[str, float]:
    """
    Extract features from setup + market data for ML scoring.
    Returns dict with risk_pts, reward_risk_ratio, reward2_risk_ratio, is_retest,
    trend_aligned, confidence_score, hour_of_day, is_premarket, body_ratio, volatility_ratio,
    plus derived scoring flags.
    """
    # Risk and reward
    if setup.direction == "LONG":
        risk_pts = setup.entry_price - setup.stop_price
        reward1_pts = setup.target1_price - setup.entry_price
        reward2_pts = setup.target2_price - setup.entry_price
    else:
        risk_pts = setup.stop_price - setup.entry_price
        reward1_pts = setup.entry_price - setup.target1_price
        reward2_pts = setup.entry_price - setup.target2_price

    reward_risk_ratio = reward1_pts / risk_pts if risk_pts > 0 else 0.0
    reward2_risk_ratio = reward2_pts / risk_pts if risk_pts > 0 else 0.0

    # Setup type
    is_retest = 1.0 if setup.setup_type == SetupType.RETEST_REVERSAL else 0.0

    # Trend alignment
    trend_aligned = 0.0
    if (setup.direction == "LONG" and trend == TrendDirection.BULLISH) or (
        setup.direction == "SHORT" and trend == TrendDirection.BEARISH
    ):
        trend_aligned = 1.0

    # Confidence
    conf_map = {"High": 1.0, "Medium": 0.5, "Low": 0.25}
    confidence_score = conf_map.get(setup.confidence, 0.5)

    # Time features (EST) - use now_est or last bar timestamp from df_1m
    dt_for_hour = None
    if now_est is not None:
        dt_for_hour = now_est.to_pydatetime() if hasattr(now_est, "to_pydatetime") else now_est
    elif not df_1m.empty and hasattr(df_1m.index[-1], "hour"):
        dt_for_hour = df_1m.index[-1]
        if hasattr(dt_for_hour, "to_pydatetime"):
            dt_for_hour = dt_for_hour.to_pydatetime()
    if dt_for_hour is not None:
        hour = dt_for_hour.hour + dt_for_hour.minute / 60.0
        hour_of_day = (hour - 7.0) / 4.0 if 7 <= hour <= 11 else 0.5
        is_premarket = 1.0 if hour < 9.5 else 0.0  # 9:30 = 9.5
        hour_8_10 = 1.0 if 8 <= hour <= 10 else 0.0
    else:
        hour_of_day = 0.5
        is_premarket = 0.5
        hour_8_10 = 0.0

    # Trigger bar (last candle) body ratio
    body_ratio = 0.0
    if not df_1m.empty:
        last = df_1m.iloc[-1]
        o, c, h, l = float(last["open"]), float(last["close"]), float(last["high"]), float(last["low"])
        body = abs(c - o)
        rng = h - l
        body_ratio = body / rng if rng > 0 else 0.0

    # Volatility ratio (current ATR / average ATR)
    volatility_ratio = 1.0
    if not df_1m.empty and len(df_1m) >= 51:
        atr_current = _atr(df_1m, period=14)
        atr_avg = _atr(df_1m, period=50)
        if atr_current is not None and atr_avg is not None and atr_avg > 0:
            volatility_ratio = atr_current / atr_avg

    # Derived scoring flags
    reward_risk_ge_1_5 = 1.0 if reward_risk_ratio >= 1.5 else 0.0
    body_ratio_gt_0_5 = 1.0 if body_ratio > 0.5 else 0.0
    low_volatility = 1.0 if volatility_ratio < 1.2 else 0.0

    return {
        "risk_pts": risk_pts,
        "reward_risk_ratio": reward_risk_ratio,
        "reward2_risk_ratio": reward2_risk_ratio,
        "is_retest": is_retest,
        "trend_aligned": trend_aligned,
        "confidence_score": confidence_score,
        "hour_of_day": hour_of_day,
        "is_premarket": is_premarket,
        "body_ratio": body_ratio,
        "volatility_ratio": volatility_ratio,
        "reward_risk_ge_1_5": reward_risk_ge_1_5,
        "hour_8_10": hour_8_10,
        "body_ratio_gt_0_5": body_ratio_gt_0_5,
        "low_volatility": low_volatility,
    }


def _load_weights() -> dict[str, float]:
    """Load weights from disk or return defaults."""
    if WEIGHTS_PATH.exists():
        try:
            data = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
            weights = data.get("weights", DEFAULT_WEIGHTS.copy())
            # Ensure all keys exist
            for k, v in DEFAULT_WEIGHTS.items():
                if k not in weights:
                    weights[k] = v
            return weights
        except Exception as e:
            logger.warning("Could not load ml_weights.json: %s; using defaults", e)
    return DEFAULT_WEIGHTS.copy()


def _save_weights(weights: dict[str, float]) -> None:
    """Persist weights to disk."""
    WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEIGHTS_PATH.write_text(
        json.dumps({"weights": weights}, indent=2),
        encoding="utf-8",
    )


def score_setup(features: dict[str, float], weights: dict[str, float] | None = None) -> float:
    """
    Compute confidence score 0.0-1.0 from features using weighted scoring.
    No heavy ML library; pure numpy-style weighted sum.
    """
    w = weights if weights is not None else _load_weights()
    score = w.get("base", 0.10)

    # trend_aligned: +weight when 1
    if features.get("trend_aligned", 0) >= 0.5:
        score += w.get("trend_aligned", 0.20)

    # confidence_score: multiply contribution (0.15 * value)
    score += w.get("confidence_score", 0.15) * features.get("confidence_score", 0.5)

    # reward_risk >= 1.5
    if features.get("reward_risk_ge_1_5", 0) >= 0.5:
        score += w.get("reward_risk_ge_1_5", 0.15)

    # is_retest
    if features.get("is_retest", 0) >= 0.5:
        score += w.get("is_retest", 0.10)

    # hour 8-10 AM
    if features.get("hour_8_10", 0) >= 0.5:
        score += w.get("hour_8_10", 0.10)

    # body_ratio > 0.5
    if features.get("body_ratio_gt_0_5", 0) >= 0.5:
        score += w.get("body_ratio_gt_0_5", 0.10)

    # low volatility (ratio < 1.2)
    if features.get("low_volatility", 0) >= 0.5:
        score += w.get("low_volatility", 0.10)

    return min(1.0, max(0.0, float(score)))


def ml_filter_check(
    setup: ReversalSetup,
    df_1m: pd.DataFrame,
    trend: TrendDirection,
    threshold: float = DEFAULT_THRESHOLD,
    now_est: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """
    Run ML filter on setup. Returns dict with pass, score, features.
    Pass if score >= threshold (default 0.5).
    """
    features = extract_features(setup, df_1m, trend, now_est)
    score = score_setup(features)
    return {
        "pass": score >= threshold,
        "score": round(score, 4),
        "features": features,
    }


def train_from_history(trade_history: list[dict]) -> None:
    """
    Adjust weights based on historical wins/losses (simple Bayesian update).
    Each trade should have: pnl (or result), and optionally features.
    Win = pnl > 0 or result in ("tp1", "tp2", "tp1_partial", "tp2_partial").
    Saves updated weights to ml_weights.json.
    """
    if not trade_history:
        return

    weights = _load_weights()
    # Track wins/losses per feature when that feature was favorable (1)
    wins: dict[str, int] = {k: 0 for k in SCORING_KEYS}
    losses: dict[str, int] = {k: 0 for k in SCORING_KEYS}

    win_results = {"tp1", "tp2", "tp1_partial", "tp2_partial", "win"}

    for t in trade_history:
        pnl = t.get("pnl", 0)
        result = str(t.get("result", "")).lower()
        is_win = pnl > 0 or result in win_results

        feats = t.get("features")
        if not feats or not isinstance(feats, dict):
            continue

        for key in SCORING_KEYS:
            if key not in feats:
                continue
            val = feats[key]
            # Feature is "favorable" when it contributes to score (1 or True or > 0.5)
            favorable = val >= 0.5 if isinstance(val, (int, float)) else bool(val)
            if not favorable:
                continue
            if is_win:
                wins[key] += 1
            else:
                losses[key] += 1

    # Bayesian update: new_weight = base * (wins + 1) / (wins + losses + 2)
    # Map scoring key to weight key (some differ)
    key_to_weight = {
        "trend_aligned": "trend_aligned",
        "confidence_score": "confidence_score",
        "reward_risk_ge_1_5": "reward_risk_ge_1_5",
        "is_retest": "is_retest",
        "hour_8_10": "hour_8_10",
        "body_ratio_gt_0_5": "body_ratio_gt_0_5",
        "low_volatility": "low_volatility",
    }

    for key in SCORING_KEYS:
        wkey = key_to_weight.get(key, key)
        if wkey not in weights:
            continue
        base = DEFAULT_WEIGHTS.get(wkey, weights[wkey])
        w, l = wins[key], losses[key]
        if w + l == 0:
            continue
        # Laplace smoothing: posterior mean
        win_rate = (w + 1) / (w + l + 2)
        # Scale: weight moves toward base * (2 * win_rate) so 50% -> 1x, 100% -> 2x, 0% -> 0
        new_weight = base * (0.5 + win_rate)
        weights[wkey] = round(min(0.5, max(0.02, new_weight)), 4)

    _save_weights(weights)
    logger.info("ML weights updated from %d trades; saved to %s", len(trade_history), WEIGHTS_PATH)
