"""
NAS100 v3.0 — Exact signal output format per spec.
"""

from __future__ import annotations

from typing import Any, Optional


def format_signal_v3(
    date_str: str,
    time_est: str,
    strategy: str,
    direction: str,
    entry: float,
    sl: float,
    sl_pts: float,
    tp1: float,
    tp2: float,
    trail_pts: float,
    risk_pct: float,
    rr_ratio: float,
    conditions_met: list[str],
    trade_num: int,
    signal_count_today: int,
) -> str:
    strategy_label = {
        "EMA_Pullback": "EMA Pullback",
        "ORB": "ORB",
        "PDH_PDL": "PDH-PDL",
    }.get(strategy, strategy)
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"DATE: {date_str}",
        "NAS100 SIGNAL",
        f"TIME: {time_est} EST",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"STRATEGY: {strategy_label}",
        f"DIRECTION: {direction}",
        f"ENTRY: {entry:.2f}",
        f"STOP LOSS: {sl:.2f} ({sl_pts:.0f} pts risk)",
        f"TP1: {tp1:.2f} — close 30% position",
        f"TP2: {tp2:.2f} — close 50% position",
        f"TP3: Trail 20% with {trail_pts:.0f}-pt trailing stop",
        f"RISK: {risk_pct:.1f}% of account",
        f"RR RATIO: 1:{rr_ratio:.1f}",
        "",
        "CONDITIONS MET:",
    ]
    for c in conditions_met:
        lines.append(f"  {c}")
    lines.append("")
    lines.append(f"TRADE#: {trade_num} of day")
    lines.append(f"SIGNAL COUNT TODAY: {signal_count_today}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def signal_from_trade_row(row: Any, trade_num: int, signal_count_today: int, conditions: Optional[list] = None) -> str:
    """Build v3 signal text from a trade row (e.g. from backtest or live)."""
    try:
        entry_time = row["entry_time"]
        date_str = entry_time.strftime("%d/%m/%Y") if hasattr(entry_time, "strftime") else str(entry_time)[:10]
        time_est = entry_time.strftime("%H:%M") if hasattr(entry_time, "strftime") else "09:30"
    except Exception:
        date_str = "01/01/2025"
        time_est = "09:30"
    entry = float(row.get("entry", 0))
    sl = float(row.get("sl", 0))
    sl_pts = abs(entry - sl)
    tp1 = entry + sl_pts * 1.0 if row.get("direction") == "BUY" else entry - sl_pts * 1.0
    tp2 = entry + sl_pts * 2.0 if row.get("direction") == "BUY" else entry - sl_pts * 2.0
    trail_pts = 20.0
    risk_pct = float(row.get("risk_pct", 1.5))
    conditions_met = conditions or ["H1 EMA 20 vs EMA 50", "Price touched EMA 20 on M15", "M15 trigger closed in trend"]
    return format_signal_v3(
        date_str=date_str,
        time_est=time_est,
        strategy=str(row.get("strategy", "EMA_Pullback")),
        direction=str(row.get("direction", "BUY")),
        entry=entry,
        sl=sl,
        sl_pts=sl_pts,
        tp1=tp1,
        tp2=tp2,
        trail_pts=trail_pts,
        risk_pct=risk_pct,
        rr_ratio=2.0,
        conditions_met=conditions_met,
        trade_num=trade_num,
        signal_count_today=signal_count_today,
    )
