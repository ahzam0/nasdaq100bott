"""
Order flow signals for the scalp strategy.

Priority:
  1. REAL data from Alpaca/Finnhub WebSocket (true volume delta, tick VWAP)
  2. CANDLE PROXY from Yahoo Finance 1m candles (estimated from candle direction)

The caller always gets a VolumeFlowSignal; the `is_real` flag tells you
which source was used.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class VolumeFlowSignal:
    vwap: float
    cvd: float
    cvd_slope: float
    volume_spike: bool
    spike_direction: str        # "BUY" | "SELL" | "NONE"
    imbalance_ratio: float      # -1 to 1
    rsi: float
    atr: float
    momentum_score: float       # -100 to 100

    # Real-time extras (populated only when is_real=True)
    is_real: bool = False
    source: str = "candle_proxy"
    tape_speed: float = 0.0
    large_order_bias: str = "NEUTRAL"
    delta_divergence: bool = False
    divergence_type: str = "none"
    absorption_detected: bool = False
    absorption_level: float = 0.0
    absorption_side: str = "NEUTRAL"
    poc_price: float = 0.0
    trade_count: int = 0


def _rsi(closes: pd.Series, period: int = 8) -> float:
    """Wilder RSI over the last `period` bars."""
    if len(closes) < period + 1:
        return 50.0
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean().iloc[-1]
    avg_loss = loss.rolling(period, min_periods=period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range over last `period` bars."""
    if len(df) < period + 1:
        return 0.0
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return float(tr.rolling(period, min_periods=period).mean().iloc[-1])


def _try_realtime_flow(df_1m: pd.DataFrame, lookback: int) -> VolumeFlowSignal | None:
    """Attempt to build a VolumeFlowSignal from real-time trade data."""
    try:
        from data.orderflow_engine import compute_realtime_flow
        flow = compute_realtime_flow(window_seconds=300)
        if flow is None or not flow.is_real or flow.trade_count < 20:
            return None
    except Exception:
        return None

    # We still compute RSI and ATR from candle data (more stable)
    rsi = _rsi(df_1m["close"].tail(lookback), period=8) if df_1m is not None and len(df_1m) >= 20 else 50.0
    atr = _atr(df_1m.tail(lookback), period=14) if df_1m is not None and len(df_1m) >= 20 else 20.0

    # Volume spike: tape speed > 2x normal = spike
    # Normal QQQ tape: ~20-50 trades/sec during RTH
    volume_spike = flow.tape_speed > 80
    if volume_spike:
        spike_direction = "BUY" if flow.volume_delta > 0 else "SELL"
    elif flow.large_order_bias in ("BUY", "SELL"):
        volume_spike = True
        spike_direction = flow.large_order_bias
    else:
        spike_direction = "NONE"

    # Momentum score from real data
    # CVD slope (normalised), VWAP position, RSI, large orders, tape speed
    cvd_norm = np.clip(flow.cvd_slope / max(abs(flow.cumulative_delta) * 0.01, 1), -1, 1)
    vwap_norm = np.clip(flow.price_vs_vwap / max(atr * 2, 1), -1, 1)
    rsi_norm = (rsi - 50) / 50
    spike_score = 0.0
    if spike_direction == "BUY":
        spike_score = 0.6
    elif spike_direction == "SELL":
        spike_score = -0.6
    large_score = 0.0
    if flow.large_order_bias == "BUY":
        large_score = 0.4
    elif flow.large_order_bias == "SELL":
        large_score = -0.4
    div_score = 0.0
    if flow.delta_divergence:
        div_score = 0.3 if flow.divergence_type == "bullish_div" else -0.3

    momentum_score = (
        cvd_norm * 30
        + vwap_norm * 20
        + rsi_norm * 10
        + spike_score * 15
        + large_score * 15
        + div_score * 10
    )
    momentum_score = float(np.clip(momentum_score, -100, 100))

    return VolumeFlowSignal(
        vwap=flow.vwap,
        cvd=flow.cumulative_delta,
        cvd_slope=flow.cvd_slope,
        volume_spike=volume_spike,
        spike_direction=spike_direction,
        imbalance_ratio=flow.imbalance_ratio,
        rsi=rsi,
        atr=atr,
        momentum_score=momentum_score,
        is_real=True,
        source=flow.source,
        tape_speed=flow.tape_speed,
        large_order_bias=flow.large_order_bias,
        delta_divergence=flow.delta_divergence,
        divergence_type=flow.divergence_type,
        absorption_detected=flow.absorption_detected,
        absorption_level=flow.absorption_level,
        absorption_side=flow.absorption_side,
        poc_price=flow.poc_price,
        trade_count=flow.trade_count,
    )


def _candle_proxy_flow(df_1m: pd.DataFrame, lookback: int) -> VolumeFlowSignal | None:
    """Fallback: estimate order flow from 1-minute candle OHLCV data."""
    if df_1m is None or len(df_1m) < max(lookback, 20):
        return None

    df = df_1m.tail(lookback).copy()
    if "volume" not in df.columns or df["volume"].sum() == 0:
        df["volume"] = 1

    body = df["close"] - df["open"]
    df["vol_delta"] = np.where(body > 0, df["volume"], np.where(body < 0, -df["volume"], 0))

    df["cvd"] = df["vol_delta"].cumsum()
    cvd_current = float(df["cvd"].iloc[-1])

    cvd_window = df["cvd"].tail(10).values
    if len(cvd_window) >= 5:
        x = np.arange(len(cvd_window))
        coeffs = np.polyfit(x, cvd_window, 1)
        cvd_slope = float(coeffs[0])
    else:
        cvd_slope = 0.0

    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    vwap_series = cum_tp_vol / cum_vol.replace(0, 1)
    vwap = float(vwap_series.iloc[-1])

    vol_ma = df["volume"].rolling(20, min_periods=5).mean()
    last_vol = float(df["volume"].iloc[-1])
    avg_vol = float(vol_ma.iloc[-1]) if not np.isnan(vol_ma.iloc[-1]) else 1.0
    volume_spike = last_vol > 2.0 * avg_vol

    last_body = float(body.iloc[-1])
    if volume_spike:
        spike_direction = "BUY" if last_body > 0 else ("SELL" if last_body < 0 else "NONE")
    else:
        spike_direction = "NONE"

    recent_buy = float(df["vol_delta"].clip(lower=0).tail(10).sum())
    recent_sell = float((-df["vol_delta"].clip(upper=0)).tail(10).sum())
    total = recent_buy + recent_sell
    imbalance_ratio = (recent_buy - recent_sell) / total if total > 0 else 0.0

    rsi = _rsi(df_1m["close"].tail(lookback), period=8)
    atr = _atr(df_1m.tail(lookback), period=14)

    cvd_norm = np.clip(cvd_slope / max(avg_vol * 0.1, 1), -1, 1)
    vwap_dev = (float(df["close"].iloc[-1]) - vwap) / max(atr, 1)
    vwap_norm = np.clip(vwap_dev / 2.0, -1, 1)
    rsi_norm = (rsi - 50) / 50
    spike_score = 0.0
    if spike_direction == "BUY":
        spike_score = 0.5
    elif spike_direction == "SELL":
        spike_score = -0.5

    momentum_score = (
        cvd_norm * 40
        + vwap_norm * 25
        + rsi_norm * 15
        + spike_score * 20
    )
    momentum_score = float(np.clip(momentum_score, -100, 100))

    return VolumeFlowSignal(
        vwap=vwap,
        cvd=cvd_current,
        cvd_slope=cvd_slope,
        volume_spike=volume_spike,
        spike_direction=spike_direction,
        imbalance_ratio=float(np.clip(imbalance_ratio, -1, 1)),
        rsi=rsi,
        atr=atr,
        momentum_score=momentum_score,
        is_real=False,
        source="candle_proxy",
    )


def compute_volume_flow(df_1m: pd.DataFrame, lookback: int = 50) -> VolumeFlowSignal | None:
    """Compute order-flow signals.

    Tries real-time data first (Alpaca/Finnhub), falls back to candle proxy.
    """
    # 1. Try real-time trade data
    signal = _try_realtime_flow(df_1m, lookback)
    if signal is not None:
        logger.debug("Volume flow: REAL data (%s, %d trades)", signal.source, signal.trade_count)
        return signal

    # 2. Fallback to candle proxy
    signal = _candle_proxy_flow(df_1m, lookback)
    if signal is not None:
        logger.debug("Volume flow: candle proxy (no real-time data)")
    return signal
