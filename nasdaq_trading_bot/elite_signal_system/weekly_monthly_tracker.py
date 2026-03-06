"""
Weekly and monthly performance tracker output format.
"""

from __future__ import annotations


def weekly_summary(
    total_signals: int,
    winners: int,
    losers: int,
    win_rate_pct: float,
    net_return_pct: float,
    drawdown_pct: float,
    profit_factor: float,
    best_trade_pct: float,
    worst_trade_pct: float,
) -> str:
    return f"""
WEEKLY SUMMARY
--------------------------------
Total Signals: {total_signals}
Winners: {winners}  |  Losers: {losers}
Win Rate: {win_rate_pct:.1f}%
Net Return: {net_return_pct:+.1f}%
Drawdown This Week: {drawdown_pct:.1f}%
Profit Factor: {profit_factor:.2f}
Best Trade: {best_trade_pct:+.1f}%
Worst Trade: {worst_trade_pct:.1f}%
--------------------------------"""


def monthly_audit(
    targets_met: bool,
    signals_per_day: float,
    win_rate_pct: float,
    monthly_return_pct: float,
    profit_factor: float,
    max_drawdown_pct: float,
    next_strategy_if_fail: str = "",
) -> str:
    status = "ALL 5 TARGETS MET." if targets_met else "TARGETS NOT MET."
    out = f"""
MONTHLY PERFORMANCE AUDIT
--------------------------------
Status: {status}
Signals/day: {signals_per_day:.2f} (target >= 1.0)
Win rate: {win_rate_pct:.1f}% (target >= 70%)
Monthly return: {monthly_return_pct:.1f}% (target >= 40%)
Profit factor: {profit_factor:.2f} (target >= 2.0)
Max drawdown: {max_drawdown_pct:.1f}% (target < 15%)
--------------------------------"""
    if not targets_met and next_strategy_if_fail:
        out += f"\nADJUSTMENTS FOR NEXT MONTH: {next_strategy_if_fail}\n"
    return out
