"""
Weekly performance tracker — exact format for NAS100.
"""

from __future__ import annotations

from nas100_elite.config import TARGETS


def format_weekly_report(
    week_start: str,
    week_end: str,
    total_signals: int,
    total_trades: int,
    trades_skipped: int,
    winners: int,
    losers: int,
    win_rate_pct: float,
    avg_win_pts: float,
    avg_loss_pts: float,
    profit_factor: float,
    starting_balance: float,
    ending_balance: float,
    weekly_return_pct: float,
    drawdown_week_pct: float,
) -> str:
    wr_ok = win_rate_pct >= TARGETS["win_rate_pct_min"]
    sig_ok = (total_trades / 5.0) >= TARGETS["signals_per_day_min"] if total_trades else False
    pf_ok = profit_factor >= TARGETS["profit_factor_min"]
    dd_ok = drawdown_week_pct <= TARGETS["max_drawdown_pct_max"]
    return f"""
==============================================================
NASDAQ WEEKLY REPORT
Week of: {week_start} to {week_end}
==============================================================
Total Signals Generated:   {total_signals}
Total Trades Taken:        {total_trades}
Trades Skipped (<5/7):     {trades_skipped}

Winners:    {winners}
Losers:     {losers}
Win Rate:   {win_rate_pct:.1f}%

Avg Win:    +{avg_win_pts:.1f} pts
Avg Loss:   -{avg_loss_pts:.1f} pts
Profit Factor: {profit_factor:.2f}

Starting Balance:  ${starting_balance:,.2f}
Ending Balance:    ${ending_balance:,.2f}
Weekly Return:     {weekly_return_pct:+.1f}%
Drawdown (week):   {drawdown_week_pct:.1f}%

TARGET STATUS:
  Win Rate >=70%:     {"OK" if wr_ok else "MISS"} ({win_rate_pct:.1f}%)
  Signals >=1/day:    {"OK" if sig_ok else "MISS"} ({total_trades / 5.0:.1f}/day avg)
  Profit Factor >=2:  {"OK" if pf_ok else "MISS"} ({profit_factor:.2f})
  Drawdown <=15%:    {"OK" if dd_ok else "MISS"} ({drawdown_week_pct:.1f}%)

ADJUSTMENTS FOR NEXT WEEK:
  [List specific changes based on this week's failures]
=============================================================="""
