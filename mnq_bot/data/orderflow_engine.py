"""
Real-time order flow computation engine.

Processes classified trades from the DataCollectorManager to compute:
  - True volume delta (buy vol - sell vol, not candle-estimated)
  - True CVD (cumulative volume delta)
  - Tick-level VWAP from actual trades
  - Large order detection (institutional footprint)
  - Tape speed (trades/second)
  - Absorption detection at price levels
  - Delta divergence (price vs delta disagreement)
  - Volume profile by price level
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class LargeOrder:
    """A detected large (institutional) trade."""
    timestamp: float
    price_nq: float
    size: int
    side: str
    multiple_of_avg: float  # how many times the average size


@dataclass
class RealTimeFlow:
    """
    Complete real-time order flow snapshot from actual trade data.
    All values computed from classified trades, NOT candle proxies.
    """
    # Core flow
    volume_delta: int            # net: buy_vol - sell_vol (over window)
    cumulative_delta: int        # session CVD
    buy_volume: int
    sell_volume: int
    imbalance_ratio: float       # -1 (all sell) to +1 (all buy)

    # VWAP
    vwap: float                  # tick-level VWAP from actual trades
    price_vs_vwap: float         # current price - VWAP (positive = above)

    # Tape analysis
    tape_speed: float            # trades per second (last 60s)
    large_orders: list[LargeOrder]  # recent large trades
    large_order_bias: str        # "BUY" | "SELL" | "NEUTRAL"

    # Delta dynamics
    cvd_slope: float             # slope of CVD over last N trades
    delta_divergence: bool       # price and delta moving opposite directions
    divergence_type: str         # "bullish_div" | "bearish_div" | "none"

    # Absorption
    absorption_detected: bool    # high volume absorbed at a price level
    absorption_level: float      # price level where absorption is happening
    absorption_side: str         # "BUY" (buyers absorbing selling) | "SELL"

    # Volume profile
    poc_price: float             # Point of Control: price with most volume
    high_vol_node: float         # highest volume node in recent window

    # Meta
    trade_count: int
    source: str                  # "Alpaca" | "Finnhub" | "none"
    data_age_seconds: float      # seconds since last trade
    is_real: bool                # True = from real trades, False = proxy


def compute_realtime_flow(window_seconds: int = 300) -> RealTimeFlow | None:
    """
    Compute real-time order flow from the global trade buffer.

    Args:
        window_seconds: lookback window in seconds (default 5 min)

    Returns:
        RealTimeFlow snapshot, or None if no real-time data available.
    """
    try:
        from data.realtime_collector import get_collector_manager
        mgr = get_collector_manager()
    except Exception:
        return None

    if not mgr.connected:
        return None

    buf = mgr.buffer
    if buf.trade_count == 0:
        return None

    now = time.time()
    cutoff = now - window_seconds
    trades = buf.get_trades_since(cutoff)

    if len(trades) < 10:
        return None

    # --- Volume Delta & CVD ---
    buy_vol = sum(t.size for t in trades if t.side == "buy")
    sell_vol = sum(t.size for t in trades if t.side == "sell")
    volume_delta = buy_vol - sell_vol

    # Session CVD from total buffer
    cumulative_delta = buf.total_buy_vol - buf.total_sell_vol

    total_vol = buy_vol + sell_vol
    imbalance = volume_delta / total_vol if total_vol > 0 else 0.0

    # --- Tick VWAP ---
    prices = np.array([t.price_nq for t in trades])
    sizes = np.array([t.size for t in trades], dtype=float)
    total_size = sizes.sum()
    vwap = float(np.sum(prices * sizes) / total_size) if total_size > 0 else prices[-1]
    current_price = trades[-1].price_nq
    price_vs_vwap = current_price - vwap

    # --- Tape Speed ---
    elapsed = trades[-1].timestamp - trades[0].timestamp
    tape_speed = len(trades) / elapsed if elapsed > 0 else 0.0

    # --- Large Orders ---
    avg_size = float(sizes.mean()) if len(sizes) > 0 else 1.0
    threshold = max(avg_size * 3.0, 500)
    large_orders = []
    large_buy_vol = 0
    large_sell_vol = 0
    for t in trades:
        if t.size >= threshold:
            mult = t.size / avg_size if avg_size > 0 else 1.0
            large_orders.append(LargeOrder(
                timestamp=t.timestamp,
                price_nq=t.price_nq,
                size=t.size,
                side=t.side,
                multiple_of_avg=mult,
            ))
            if t.side == "buy":
                large_buy_vol += t.size
            else:
                large_sell_vol += t.size

    large_orders = large_orders[-20:]  # keep last 20
    if large_buy_vol > large_sell_vol * 1.5:
        large_order_bias = "BUY"
    elif large_sell_vol > large_buy_vol * 1.5:
        large_order_bias = "SELL"
    else:
        large_order_bias = "NEUTRAL"

    # --- CVD Slope (linear regression over last 200 trades) ---
    recent = trades[-200:] if len(trades) > 200 else trades
    running_delta = []
    cum = 0
    for t in recent:
        cum += t.size if t.side == "buy" else -t.size
        running_delta.append(cum)
    cvd_arr = np.array(running_delta, dtype=float)
    if len(cvd_arr) >= 5:
        x = np.arange(len(cvd_arr))
        coeffs = np.polyfit(x, cvd_arr, 1)
        cvd_slope = float(coeffs[0])
    else:
        cvd_slope = 0.0

    # --- Delta Divergence ---
    # Price trending up but delta trending down = bearish divergence
    # Price trending down but delta trending up = bullish divergence
    price_arr = np.array([t.price_nq for t in recent])
    if len(price_arr) >= 10:
        price_slope = float(np.polyfit(np.arange(len(price_arr)), price_arr, 1)[0])
        delta_divergence = (
            (price_slope > 0.5 and cvd_slope < -50) or
            (price_slope < -0.5 and cvd_slope > 50)
        )
        if delta_divergence:
            divergence_type = "bullish_div" if price_slope < 0 and cvd_slope > 0 else "bearish_div"
        else:
            divergence_type = "none"
    else:
        delta_divergence = False
        divergence_type = "none"

    # --- Absorption Detection ---
    # High volume concentrated at a narrow price range = absorption
    price_buckets: dict[int, dict] = defaultdict(lambda: {"buy": 0, "sell": 0, "total": 0})
    bucket_size = 5  # 5 NQ points per bucket
    for t in trades:
        bucket = int(t.price_nq / bucket_size) * bucket_size
        price_buckets[bucket][t.side] += t.size
        price_buckets[bucket]["total"] += t.size

    absorption_detected = False
    absorption_level = 0.0
    absorption_side = "NEUTRAL"

    if price_buckets:
        avg_bucket_vol = total_vol / max(len(price_buckets), 1)
        for level, vols in price_buckets.items():
            if vols["total"] > avg_bucket_vol * 3:
                absorption_detected = True
                absorption_level = float(level)
                if vols["buy"] > vols["sell"] * 2:
                    absorption_side = "BUY"
                elif vols["sell"] > vols["buy"] * 2:
                    absorption_side = "SELL"
                break

    # --- Volume Profile / POC ---
    if price_buckets:
        poc_bucket = max(price_buckets.items(), key=lambda x: x[1]["total"])
        poc_price = float(poc_bucket[0])
        sorted_buckets = sorted(price_buckets.items(), key=lambda x: x[1]["total"], reverse=True)
        high_vol_node = float(sorted_buckets[0][0]) if sorted_buckets else poc_price
    else:
        poc_price = current_price
        high_vol_node = current_price

    # --- Data freshness ---
    last_trade_ts = trades[-1].timestamp
    data_age = now - last_trade_ts

    return RealTimeFlow(
        volume_delta=volume_delta,
        cumulative_delta=cumulative_delta,
        buy_volume=buy_vol,
        sell_volume=sell_vol,
        imbalance_ratio=float(np.clip(imbalance, -1, 1)),
        vwap=vwap,
        price_vs_vwap=price_vs_vwap,
        tape_speed=tape_speed,
        large_orders=large_orders,
        large_order_bias=large_order_bias,
        cvd_slope=cvd_slope,
        delta_divergence=delta_divergence,
        divergence_type=divergence_type,
        absorption_detected=absorption_detected,
        absorption_level=absorption_level,
        absorption_side=absorption_side,
        poc_price=poc_price,
        high_vol_node=high_vol_node,
        trade_count=len(trades),
        source=mgr.source,
        data_age_seconds=data_age,
        is_real=True,
    )
