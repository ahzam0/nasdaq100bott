"""
Hybrid: ORB for morning (first signal), OB for afternoon (second signal). >= 1 signal per day.
"""

from __future__ import annotations

from typing import List, Tuple

import pandas as pd

from nas100_elite.strategies.orb import generate_orb_entries
from nas100_elite.strategies.order_block import generate_ob_entries
from nas100_elite.strategies.key_level import generate_key_level_entries


def generate_hybrid_entries(
    df: pd.DataFrame,
) -> List[Tuple[int, str, float, float, float, float, float, float, str, int]]:
    """
    Combine ORB + OB + Key Level; dedupe by bar; ensure at least one entry per day when possible.
    """
    if df is None or len(df) < 20:
        return []
    orb = generate_orb_entries(df, atr_min_points=15.0, min_bars_apart=1)
    ob = generate_ob_entries(df, min_bars_apart=1)
    key = generate_key_level_entries(df, min_bars_apart=1)
    seen_bar = set()
    combined = []
    for e in orb + ob + key:
        if e[0] in seen_bar:
            continue
        seen_bar.add(e[0])
        combined.append(e)
    combined.sort(key=lambda x: x[0])
    try:
        entry_dates = set()
        for e in combined:
            try:
                entry_dates.add(df.index[e[0]].date())
            except Exception:
                entry_dates.add(e[0])
    except Exception:
        entry_dates = set()
    for i in range(2, len(df) - 1):
        if i in seen_bar:
            continue
        try:
            d = df.index[i].date()
        except Exception:
            d = i
        if d not in entry_dates:
            close = float(df["close"].iloc[i])
            atr = (df["high"] - df["low"]).rolling(14).mean().iloc[i]
            if pd.isna(atr) or atr <= 0:
                atr = 30.0
            sl_pts = min(80.0, max(20.0, float(atr)))
            combined.append((i, "BUY", close, close - sl_pts, close + sl_pts * 2, close + sl_pts * 3, 30.0, 1.0, "HybridFallback", 5))
            entry_dates.add(d)
            seen_bar.add(i)
    combined.sort(key=lambda x: x[0])
    return combined


class HybridNAS100Strategy:
    def generate_entries(self, df: pd.DataFrame) -> List[Tuple[int, str, float, float, float, float, float, float, str, int]]:
        return generate_hybrid_entries(df)
