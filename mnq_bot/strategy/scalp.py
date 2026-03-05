"""
Quick-scalp strategy using real-time order flow signals.

When real-time data is available (Alpaca/Finnhub), uses:
  - True volume delta & CVD from classified trades
  - Tick-level VWAP from actual trade prices
  - Large order (institutional) detection
  - Tape speed analysis
  - Delta divergence signals
  - Absorption detection at key levels

Falls back to candle-proxy signals when no real-time data.

Entry types:
  1. VWAP Bounce      – price near VWAP + volume confirms direction
  2. Delta Momentum   – strong CVD slope + volume spike
  3. Volume Spike     – outlier volume with directional body
  4. Large Order      – institutional trade confirms direction (REAL only)
  5. Delta Divergence – price/delta disagreement at extreme (REAL only)
  6. Absorption       – high volume absorbed at a key level (REAL only)

Targets: 40-80 pts.  Hold time: 10-30 minutes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from strategy.volume_flow import VolumeFlowSignal
from strategy.market_structure import SwingPoint

logger = logging.getLogger(__name__)

# Avoid circular import – SmartMoneyScore is only used for type hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from strategy.smart_money import SmartMoneyScore


class ScalpSignalType(str, Enum):
    VWAP_BOUNCE = "VWAP_Bounce"
    DELTA_MOMENTUM = "Delta_Momentum"
    VOLUME_SPIKE = "Volume_Spike"
    LARGE_ORDER = "Large_Order"
    DELTA_DIVERGENCE = "Delta_Divergence"
    ABSORPTION = "Absorption"


@dataclass
class ScalpSetup:
    direction: str              # "LONG" | "SHORT"
    entry_price: float
    stop_price: float
    target1_price: float
    target2_price: float
    confidence: str             # "High" | "Medium"
    signal_type: str            # ScalpSignalType value
    momentum_score: float
    notes: str
    setup_type: ScalpSignalType = ScalpSignalType.VWAP_BOUNCE
    key_level_name: str = "VWAP"
    trend_15m: object = None


def _nearest_swing_low(swing_lows: list[SwingPoint], price: float, max_dist: float = 120) -> float | None:
    candidates = [s.price for s in swing_lows if s.price < price and price - s.price <= max_dist]
    return max(candidates) if candidates else None


def _nearest_swing_high(swing_highs: list[SwingPoint], price: float, max_dist: float = 120) -> float | None:
    candidates = [s.price for s in swing_highs if s.price > price and s.price - price <= max_dist]
    return min(candidates) if candidates else None


def detect_scalp(
    df_1m: pd.DataFrame,
    flow: VolumeFlowSignal,
    swing_highs: list[SwingPoint],
    swing_lows: list[SwingPoint],
    tp1_pts: float = 40.0,
    tp2_pts: float = 80.0,
    max_risk_pts: float = 60.0,
    min_atr: float = 15.0,
    momentum_threshold: float = 40.0,
    smart_money: "SmartMoneyScore | None" = None,
) -> ScalpSetup | None:
    """Detect a scalp entry from volume-flow signals (real or proxy).

    When *smart_money* is provided, only take trades where the Smart Money
    directional bias agrees with the signal direction (or is neutral with
    high confidence).  This dramatically improves win rate.
    """
    if flow is None or df_1m is None or len(df_1m) < 20:
        return None

    price = float(df_1m["close"].iloc[-1])
    atr = flow.atr

    if atr < min_atr:
        logger.debug("Scalp skip: ATR %.1f < min %.1f", atr, min_atr)
        return None

    vwap = flow.vwap
    vwap_dist = price - vwap
    rsi = flow.rsi
    ms = flow.momentum_score
    is_real = flow.is_real

    setup: ScalpSetup | None = None

    # ── REAL-DATA-ONLY signals (highest confidence) ────────────────────

    if is_real:
        # 4. Large Order – institutional footprint confirms direction
        if flow.large_order_bias == "BUY" and ms > 15 and rsi < 72:
            setup = _build_long(price, flow, swing_lows, tp1_pts, tp2_pts, max_risk_pts,
                                ScalpSignalType.LARGE_ORDER, "High",
                                f"Large order BUY detected | tape {flow.tape_speed:.0f} t/s | score {ms:+.0f}")
        elif flow.large_order_bias == "SELL" and ms < -15 and rsi > 28:
            setup = _build_short(price, flow, swing_highs, tp1_pts, tp2_pts, max_risk_pts,
                                 ScalpSignalType.LARGE_ORDER, "High",
                                 f"Large order SELL detected | tape {flow.tape_speed:.0f} t/s | score {ms:+.0f}")

        # 5. Delta Divergence – price/delta disagreement (reversal signal)
        if setup is None and flow.delta_divergence:
            if flow.divergence_type == "bullish_div" and rsi < 40:
                setup = _build_long(price, flow, swing_lows, tp1_pts, tp2_pts, max_risk_pts,
                                    ScalpSignalType.DELTA_DIVERGENCE, "High",
                                    f"Bullish delta divergence | price falling but buying increasing")
            elif flow.divergence_type == "bearish_div" and rsi > 60:
                setup = _build_short(price, flow, swing_highs, tp1_pts, tp2_pts, max_risk_pts,
                                     ScalpSignalType.DELTA_DIVERGENCE, "High",
                                     f"Bearish delta divergence | price rising but selling increasing")

        # 6. Absorption – high volume absorbed at a key price level
        if setup is None and flow.absorption_detected:
            dist_to_absorption = abs(price - flow.absorption_level)
            if dist_to_absorption < 20:
                if flow.absorption_side == "BUY" and ms > 10:
                    setup = _build_long(price, flow, swing_lows, tp1_pts, tp2_pts, max_risk_pts,
                                        ScalpSignalType.ABSORPTION, "High",
                                        f"Buy absorption @ {flow.absorption_level:.0f} | sellers absorbed")
                elif flow.absorption_side == "SELL" and ms < -10:
                    setup = _build_short(price, flow, swing_highs, tp1_pts, tp2_pts, max_risk_pts,
                                         ScalpSignalType.ABSORPTION, "High",
                                         f"Sell absorption @ {flow.absorption_level:.0f} | buyers absorbed")

    # ── Standard signals (work with both real and proxy data) ──────────

    # 1. VWAP Bounce – price near VWAP + volume confirms direction
    if setup is None and abs(vwap_dist) <= 20:
        # With real data: require stronger confirmation (tape speed, large orders)
        min_ms = 15 if is_real else 20
        if flow.cvd_slope > 0 and ms > min_ms and 30 < rsi < 70:
            conf = "High" if (is_real and flow.tape_speed > 40) else ("High" if ms > 50 else "Medium")
            extra = f" | tape {flow.tape_speed:.0f} t/s" if is_real else ""
            setup = _build_long(price, flow, swing_lows, tp1_pts, tp2_pts, max_risk_pts,
                                ScalpSignalType.VWAP_BOUNCE, conf,
                                f"VWAP bounce long | VWAP {vwap:.0f} | CVD slope +{flow.cvd_slope:.0f}{extra}")
        elif flow.cvd_slope < 0 and ms < -min_ms and 30 < rsi < 70:
            conf = "High" if (is_real and flow.tape_speed > 40) else ("High" if ms < -50 else "Medium")
            extra = f" | tape {flow.tape_speed:.0f} t/s" if is_real else ""
            setup = _build_short(price, flow, swing_highs, tp1_pts, tp2_pts, max_risk_pts,
                                 ScalpSignalType.VWAP_BOUNCE, conf,
                                 f"VWAP bounce short | VWAP {vwap:.0f} | CVD slope {flow.cvd_slope:.0f}{extra}")

    # 2. Delta Momentum – strong CVD slope + volume spike
    if setup is None and flow.volume_spike:
        if flow.spike_direction == "BUY" and flow.cvd_slope > 0 and ms > momentum_threshold and rsi < 72:
            conf = "High"
            extra = f" | {flow.trade_count} trades" if is_real else ""
            setup = _build_long(price, flow, swing_lows, tp1_pts, tp2_pts, max_risk_pts,
                                ScalpSignalType.DELTA_MOMENTUM, conf,
                                f"Delta momentum long | spike BUY | score {ms:.0f}{extra}")
        elif flow.spike_direction == "SELL" and flow.cvd_slope < 0 and ms < -momentum_threshold and rsi > 28:
            conf = "High"
            extra = f" | {flow.trade_count} trades" if is_real else ""
            setup = _build_short(price, flow, swing_highs, tp1_pts, tp2_pts, max_risk_pts,
                                 ScalpSignalType.DELTA_MOMENTUM, conf,
                                 f"Delta momentum short | spike SELL | score {ms:.0f}{extra}")

    # 3. Pure Volume Spike – outlier volume + directional body
    if setup is None and flow.volume_spike and abs(ms) > momentum_threshold * 0.8:
        if flow.spike_direction == "BUY" and ms > 0 and rsi < 68:
            setup = _build_long(price, flow, swing_lows, tp1_pts, tp2_pts, max_risk_pts,
                                ScalpSignalType.VOLUME_SPIKE, "Medium",
                                f"Volume spike long | imbalance {flow.imbalance_ratio:+.2f}")
        elif flow.spike_direction == "SELL" and ms < 0 and rsi > 32:
            setup = _build_short(price, flow, swing_highs, tp1_pts, tp2_pts, max_risk_pts,
                                 ScalpSignalType.VOLUME_SPIKE, "Medium",
                                 f"Volume spike short | imbalance {flow.imbalance_ratio:+.2f}")

    # If we got a setup from real data, tag it
    if setup is not None and is_real:
        setup.notes = f"[REAL {flow.source}] {setup.notes}"

    # ── Smart Money confirmation ──────────────────────────────────────
    if setup is not None and smart_money is not None:
        sm_score = smart_money.score
        sm_bias = smart_money.bias
        sm_conf = smart_money.confidence

        is_long = setup.direction == "LONG"
        is_short = setup.direction == "SHORT"

        # Strong disagreement: skip the trade
        if is_long and sm_bias in ("STRONG_BEAR", "BEAR") and sm_score < -25:
            logger.info("Scalp LONG rejected: Smart Money %s (%.0f)", sm_bias, sm_score)
            return None
        if is_short and sm_bias in ("STRONG_BULL", "BULL") and sm_score > 25:
            logger.info("Scalp SHORT rejected: Smart Money %s (%.0f)", sm_bias, sm_score)
            return None

        # Agreement: boost confidence
        if is_long and sm_score > 20:
            setup.confidence = "High"
            setup.notes += f" | SM {sm_bias} ({sm_score:+.0f})"
        elif is_short and sm_score < -20:
            setup.confidence = "High"
            setup.notes += f" | SM {sm_bias} ({sm_score:+.0f})"
        elif abs(sm_score) <= 20:
            # Neutral: keep existing confidence
            setup.notes += f" | SM NEUTRAL ({sm_score:+.0f})"
        else:
            # Mild disagreement: downgrade to Medium
            if setup.confidence == "High":
                setup.confidence = "Medium"
            setup.notes += f" | SM {sm_bias} ({sm_score:+.0f}) caution"

    return setup


# ---------------------------------------------------------------------------
# Build helpers
# ---------------------------------------------------------------------------

def _build_long(
    price: float,
    flow: VolumeFlowSignal,
    swing_lows: list[SwingPoint],
    tp1_pts: float,
    tp2_pts: float,
    max_risk_pts: float,
    signal_type: ScalpSignalType,
    confidence: str,
    notes: str,
) -> ScalpSetup | None:
    swing_low = _nearest_swing_low(swing_lows, price)
    if swing_low is not None:
        stop = min(swing_low - 2, price - 20)
    else:
        stop = price - 40

    risk = price - stop
    if risk > max_risk_pts:
        stop = price - max_risk_pts
        risk = max_risk_pts
    if risk < 8:
        return None

    return ScalpSetup(
        direction="LONG",
        entry_price=price,
        stop_price=stop,
        target1_price=price + tp1_pts,
        target2_price=price + tp2_pts,
        confidence=confidence,
        signal_type=signal_type.value,
        momentum_score=flow.momentum_score,
        notes=notes,
        setup_type=signal_type,
        key_level_name=_level_name(signal_type, flow),
    )


def _build_short(
    price: float,
    flow: VolumeFlowSignal,
    swing_highs: list[SwingPoint],
    tp1_pts: float,
    tp2_pts: float,
    max_risk_pts: float,
    signal_type: ScalpSignalType,
    confidence: str,
    notes: str,
) -> ScalpSetup | None:
    swing_high = _nearest_swing_high(swing_highs, price)
    if swing_high is not None:
        stop = max(swing_high + 2, price + 20)
    else:
        stop = price + 40

    risk = stop - price
    if risk > max_risk_pts:
        stop = price + max_risk_pts
        risk = max_risk_pts
    if risk < 8:
        return None

    return ScalpSetup(
        direction="SHORT",
        entry_price=price,
        stop_price=stop,
        target1_price=price - tp1_pts,
        target2_price=price - tp2_pts,
        confidence=confidence,
        signal_type=signal_type.value,
        momentum_score=flow.momentum_score,
        notes=notes,
        setup_type=signal_type,
        key_level_name=_level_name(signal_type, flow),
    )


def _level_name(signal_type: ScalpSignalType, flow: VolumeFlowSignal) -> str:
    if signal_type == ScalpSignalType.VWAP_BOUNCE:
        return "VWAP"
    if signal_type == ScalpSignalType.ABSORPTION:
        return f"Absorption@{flow.absorption_level:.0f}"
    if signal_type in (ScalpSignalType.LARGE_ORDER, ScalpSignalType.DELTA_DIVERGENCE):
        return "OrderFlow"
    return "Volume"
