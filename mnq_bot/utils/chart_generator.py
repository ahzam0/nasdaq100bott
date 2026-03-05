"""
Generate chart images with price action and key levels for Telegram /chart command.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def generate_price_chart(
    df_1m: pd.DataFrame,
    key_levels: object = None,
    active_trades: list[dict] | None = None,
    title: str = "MNQ - 1min Chart",
    last_n: int = 60,
) -> bytes:
    """
    Generate a candlestick-style chart with key levels and trade markers.
    Returns PNG bytes for Telegram send_photo.
    """
    if df_1m.empty:
        return _empty_chart("No data available")

    df = df_1m.tail(last_n).copy()
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    x = np.arange(len(df))
    opens = df["open"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    closes = df["close"].values.astype(float)

    colors = ["#00ff88" if c >= o else "#ff4444" for o, c in zip(opens, closes)]

    for i in range(len(df)):
        ax.plot([x[i], x[i]], [lows[i], highs[i]], color=colors[i], linewidth=0.8)
        body_bottom = min(opens[i], closes[i])
        body_height = abs(closes[i] - opens[i])
        ax.bar(x[i], body_height, bottom=body_bottom, width=0.6, color=colors[i], edgecolor=colors[i])

    if key_levels is not None:
        level_items = []
        if getattr(key_levels, "prev_day_high", None):
            level_items.append(("PDH", key_levels.prev_day_high, "#ffaa00"))
        if getattr(key_levels, "prev_day_low", None):
            level_items.append(("PDL", key_levels.prev_day_low, "#ffaa00"))
        if getattr(key_levels, "prev_day_close", None):
            level_items.append(("PDC", key_levels.prev_day_close, "#aa88ff"))
        if getattr(key_levels, "seven_am_high", None):
            level_items.append(("7AM H", key_levels.seven_am_high, "#00ccff"))
        if getattr(key_levels, "seven_am_low", None):
            level_items.append(("7AM L", key_levels.seven_am_low, "#00ccff"))
        if getattr(key_levels, "session_open_high", None):
            level_items.append(("OR H", key_levels.session_open_high, "#ff66cc"))
        if getattr(key_levels, "session_open_low", None):
            level_items.append(("OR L", key_levels.session_open_low, "#ff66cc"))

        for label, price, color in level_items:
            ax.axhline(y=price, color=color, linestyle="--", linewidth=0.8, alpha=0.7)
            ax.text(len(df) - 1, price, f"  {label} {price:,.0f}", color=color, fontsize=7, va="center")

    if active_trades:
        for t in active_trades:
            trade = t.get("trade")
            if not trade:
                continue
            entry = getattr(trade, "entry", t.get("entry"))
            stop = getattr(trade, "current_stop", t.get("stop"))
            direction = getattr(trade, "direction", t.get("direction", ""))
            if entry:
                color = "#00ff88" if direction == "LONG" else "#ff4444"
                ax.axhline(y=entry, color=color, linestyle="-", linewidth=1.2, alpha=0.8)
                ax.text(0, entry, f" {direction} {entry:,.0f}", color=color, fontsize=8, fontweight="bold", va="center")
            if stop:
                ax.axhline(y=stop, color="#ff4444", linestyle=":", linewidth=1, alpha=0.6)

    step = max(1, len(df) // 10)
    tick_indices = list(range(0, len(df), step))
    timestamps = df.index
    ax.set_xticks([x[i] for i in tick_indices])
    labels = []
    for i in tick_indices:
        ts = timestamps[i]
        if hasattr(ts, "strftime"):
            labels.append(ts.strftime("%H:%M"))
        else:
            labels.append(str(ts)[-8:-3])
    ax.set_xticklabels(labels, rotation=45, ha="right", color="#a0a0a0", fontsize=8)

    ax.set_title(title, color="#e8e8e8", fontsize=14, fontweight="bold")
    ax.set_ylabel("Price", color="#a0a0a0")
    ax.tick_params(colors="#a0a0a0")
    ax.grid(True, alpha=0.15, color="#ffffff")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["bottom"].set_color("#333")
    ax.spines["left"].set_color("#333")

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="PNG", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def _empty_chart(message: str) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 4))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=14, color="#a0a0a0")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="PNG", dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
