"""
Backtest engine for Riley Coleman MNQ strategy.
Runs strategy bar-by-bar with configurable balance and risk.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from config import MAX_TRADES_PER_DAY, MIN_RR_RATIO, TICK_VALUE_USD, FALLBACK_AFTER_MINUTES, FALLBACK_MIN_RR
from strategy import (
    build_key_levels,
    detect_setup,
    swing_highs_lows,
    trend_from_structure,
    validate_entry,
    next_milestone_to_trail,
    stop_for_milestone,
)
from strategy.trade_manager import ActiveTrade

from utils.risk_calculator import contracts_from_risk

logger = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")


@dataclass
class BacktestTrade:
    entry_time: datetime
    direction: str
    entry: float
    stop: float
    target1: float
    target2: float
    contracts: int
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""  # "stop" | "tp1" | "tp2" | "trail"
    pnl: float = 0.0
    partial_pnl: float = 0.0  # P&L from 50% at TP1
    r_multiple: float = 0.0


@dataclass
class BacktestResult:
    initial_balance: float
    final_balance: float
    total_return_pct: float
    total_trades: int
    winners: int
    losers: int
    win_rate_pct: float
    max_drawdown_pct: float
    max_drawdown_usd: float
    profit_factor: float
    avg_r_per_trade: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)


def _in_session(t: datetime) -> bool:
    """True if time is in 7:00–11:00 EST (session window)."""
    if t.tzinfo is None:
        t = t.replace(tzinfo=EST)
    else:
        t = t.astimezone(EST)
    h, m = t.hour, t.minute
    mins = h * 60 + m
    return 7 * 60 <= mins <= 11 * 60  # 7:00 through 11:00


def _trades_today_before(trades: list[BacktestTrade], before_time: datetime) -> int:
    before_date = before_time.astimezone(EST).date()
    return sum(
        1 for t in trades
        if t.entry_time.astimezone(EST).date() == before_date
    )


class BacktestEngine:
    def __init__(
        self,
        initial_balance: float = 50_000.0,
        risk_per_trade_usd: float = 75.0,
        max_trades_per_day: int = MAX_TRADES_PER_DAY,
        min_rr: float = MIN_RR_RATIO,
        tick_value: float = TICK_VALUE_USD,
        level_tolerance_pts: float = 8.0,
        require_trend_only: bool = False,
        skip_first_minutes: int = 0,
        retest_only: bool = False,
        min_body_pts: float = 0.0,
        max_drawdown_cap_pct: float | None = None,
        max_risk_pts: float | None = None,
        fallback_after_minutes: int = 0,
        fallback_min_rr: float | None = None,
        use_orderflow_proxy: bool = False,
    ):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.risk_per_trade_usd = risk_per_trade_usd
        self.max_trades_per_day = max_trades_per_day
        self.min_rr = min_rr
        self.tick_value = tick_value
        self.level_tolerance_pts = level_tolerance_pts
        self.require_trend_only = require_trend_only
        self.skip_first_minutes = skip_first_minutes
        self.retest_only = retest_only
        self.min_body_pts = min_body_pts
        self.max_drawdown_cap_pct = max_drawdown_cap_pct  # Stop new entries when DD from peak >= this
        self.max_risk_pts = max_risk_pts  # Skip trades with stop wider than this (limits loss per trade)
        self.fallback_after_minutes = fallback_after_minutes  # 0 = off; else after N min from 7:00, if 0 trades use fallback_min_rr
        self.fallback_min_rr = fallback_min_rr
        self.use_orderflow_proxy = use_orderflow_proxy
        self.trades: list[BacktestTrade] = []
        self.open_trades: list[tuple[ActiveTrade, BacktestTrade]] = []
        self.equity_curve: list[tuple[datetime, float]] = []
        self._last_bar_ts: datetime | None = None
        self._equity_peak: float = initial_balance

    def _get_lookback_1m_iloc(self, df_1m: pd.DataFrame, i: int) -> pd.DataFrame:
        """Last 100 1m bars up to and including bar i."""
        start = max(0, i - 99)
        return df_1m.iloc[start : i + 1]

    def _get_lookback_15m_iloc(self, df_15m: pd.DataFrame, bar_ts: pd.Timestamp) -> pd.DataFrame:
        """Last 50 15m bars up to bar_ts."""
        try:
            loc = df_15m.index.get_indexer([bar_ts], method="ffill")[0]
            start = max(0, loc - 49)
            return df_15m.iloc[start : loc + 1]
        except Exception:
            return pd.DataFrame()

    def _try_open_trade(
        self,
        setup,
        now_est: datetime,
        df_1m: pd.DataFrame,
        df_15m: pd.DataFrame,
        effective_min_rr: float | None = None,
    ) -> bool:
        min_rr_use = effective_min_rr if effective_min_rr is not None else self.min_rr
        orderflow_summary = None
        if self.use_orderflow_proxy and not df_1m.empty:
            last = df_1m.iloc[-1]
            o, c = float(last["open"]), float(last["close"])
            if c > o:
                imb = 0.5
            elif c < o:
                imb = -0.5
            else:
                imb = 0.0
            orderflow_summary = {"imbalance_ratio": imb, "age_seconds": 0}
        result = validate_entry(
            setup, now_est, _trades_today_before(self.trades, now_est),
            self.max_trades_per_day, min_rr_ratio=min_rr_use,
            orderflow_summary=orderflow_summary,
        )
        if not result.valid:
            return False
        risk_pts = abs(setup.entry_price - setup.stop_price)
        if risk_pts <= 0:
            return False
        if self.max_risk_pts is not None and risk_pts > self.max_risk_pts:
            return False
        contracts = contracts_from_risk(self.risk_per_trade_usd, risk_pts, self.tick_value)
        if contracts < 1:
            return False
        reward_pts = abs(setup.target1_price - setup.entry_price)
        if reward_pts / risk_pts < min_rr_use:
            return False
        active = ActiveTrade(
            direction=setup.direction,
            entry=setup.entry_price,
            stop=setup.stop_price,
            target1=setup.target1_price,
            target2=setup.target2_price,
            contracts=contracts,
            risk_per_contract_usd=risk_pts * self.tick_value,
        )
        bt = BacktestTrade(
            entry_time=now_est,
            direction=setup.direction,
            entry=setup.entry_price,
            stop=setup.stop_price,
            target1=setup.target1_price,
            target2=setup.target2_price,
            contracts=contracts,
        )
        self.open_trades.append((active, bt))
        return True

    def _update_open_trades(self, bar: pd.Series, bar_ts: pd.Timestamp, high: float, low: float, close: float):
        """Check stop, TP1, TP2, trailing; close trades and update balance."""
        to_remove = []
        for active, bt in self.open_trades:
            if active.direction == "LONG":
                # Stop hit first (intrabar: low touches stop)
                if low <= active.current_stop:
                    pnl = (active.current_stop - active.entry) * self.tick_value * active.contracts
                    self.balance += pnl
                    bt.exit_time = bar_ts.to_pydatetime()
                    bt.exit_price = active.current_stop
                    bt.exit_reason = "stop"
                    bt.pnl = pnl
                    bt.r_multiple = active.rr_at_price(active.current_stop)
                    self.trades.append(bt)
                    to_remove.append((active, bt))
                    continue
                # TP2 (full exit)
                if high >= active.target2:
                    pnl = (active.target2 - active.entry) * self.tick_value * active.contracts
                    self.balance += pnl
                    bt.exit_time = bar_ts.to_pydatetime()
                    bt.exit_price = active.target2
                    bt.exit_reason = "tp2"
                    bt.pnl = pnl
                    bt.r_multiple = active.rr_at_price(active.target2)
                    self.trades.append(bt)
                    to_remove.append((active, bt))
                    continue
                # TP1 (50% + breakeven)
                if not active.partial_filled and high >= active.target1:
                    half = active.contracts // 2
                    if half >= 1:
                        partial_pnl = (active.target1 - active.entry) * self.tick_value * half
                        self.balance += partial_pnl
                        bt.partial_pnl = partial_pnl
                    active.partial_filled = True
                    active.current_stop = active.entry  # breakeven
                    active.last_trailed_r = 1.0
                # Trailing: new R milestone
                r = active.rr_at_price(close)
                next_m = next_milestone_to_trail(r, active.last_trailed_r)
                if next_m is not None:
                    active.current_stop = stop_for_milestone(active, next_m)
                    active.last_trailed_r = next_m
            else:
                # SHORT
                if high >= active.current_stop:
                    pnl = (active.entry - active.current_stop) * self.tick_value * active.contracts
                    self.balance += pnl
                    bt.exit_time = bar_ts.to_pydatetime()
                    bt.exit_price = active.current_stop
                    bt.exit_reason = "stop"
                    bt.pnl = pnl
                    bt.r_multiple = active.rr_at_price(active.current_stop)
                    self.trades.append(bt)
                    to_remove.append((active, bt))
                    continue
                if low <= active.target2:
                    pnl = (active.entry - active.target2) * self.tick_value * active.contracts
                    self.balance += pnl
                    bt.exit_time = bar_ts.to_pydatetime()
                    bt.exit_price = active.target2
                    bt.exit_reason = "tp2"
                    bt.pnl = pnl
                    bt.r_multiple = active.rr_at_price(active.target2)
                    self.trades.append(bt)
                    to_remove.append((active, bt))
                    continue
                if not active.partial_filled and low <= active.target1:
                    half = active.contracts // 2
                    if half >= 1:
                        partial_pnl = (active.entry - active.target1) * self.tick_value * half
                        self.balance += partial_pnl
                        bt.partial_pnl = partial_pnl
                    active.partial_filled = True
                    active.current_stop = active.entry
                    active.last_trailed_r = 1.0
                r = active.rr_at_price(close)
                next_m = next_milestone_to_trail(r, active.last_trailed_r)
                if next_m is not None:
                    active.current_stop = stop_for_milestone(active, next_m)
                    active.last_trailed_r = next_m
        for pair in to_remove:
            self.open_trades.remove(pair)

    def run(self, df_1m: pd.DataFrame, df_15m: pd.DataFrame) -> BacktestResult:
        """Run backtest over 1m bars. df_1m and df_15m must have DatetimeIndex (prefer EST)."""
        self.balance = self.initial_balance
        self.trades = []
        self.open_trades = []
        self.equity_curve = []
        if df_1m.index.tzinfo is None:
            df_1m = df_1m.copy()
            df_1m.index = df_1m.index.tz_localize(EST)
        if df_15m.index.tzinfo is None:
            df_15m = df_15m.copy()
            df_15m.index = df_15m.index.tz_localize(EST)

        for i in range(99, len(df_1m)):  # Need enough lookback
            bar_ts = df_1m.index[i]
            bar = df_1m.iloc[i]
            now_est = bar_ts.to_pydatetime() if hasattr(bar_ts, "to_pydatetime") else bar_ts
            if not _in_session(now_est):
                if i % 20 == 0:
                    self.equity_curve.append((now_est, self.balance))
                continue

            high = float(bar["high"])
            low = float(bar["low"])
            close = float(bar["close"])

            # Update open trades (stop, TP, trail)
            self._update_open_trades(bar, bar_ts, high, low, close)
            if self.balance > self._equity_peak:
                self._equity_peak = self.balance

            # Drawdown cap: stop new entries when drawdown from peak exceeds cap
            if self.max_drawdown_cap_pct is not None and self._equity_peak > 0:
                dd_pct = (self._equity_peak - self.balance) / self._equity_peak * 100
                if dd_pct >= self.max_drawdown_cap_pct:
                    if i % 20 == 0:
                        self.equity_curve.append((now_est, self.balance))
                    continue

            # New entry only on closed bar
            lookback_1m = self._get_lookback_1m_iloc(df_1m, i)
            lookback_15m = self._get_lookback_15m_iloc(df_15m, bar_ts)
            if lookback_15m.empty or len(lookback_1m) < 5 or len(lookback_15m) < 5:
                if i % 20 == 0:
                    self.equity_curve.append((now_est, self.balance))
                continue

            # Skip first N minutes of session (avoid opening chop)
            if self.skip_first_minutes > 0:
                mins_of_day = now_est.hour * 60 + now_est.minute
                if (7 * 60 <= mins_of_day < 7 * 60 + self.skip_first_minutes or
                    9 * 60 + 30 <= mins_of_day < 9 * 60 + 30 + self.skip_first_minutes):
                    if i % 20 == 0:
                        self.equity_curve.append((now_est, self.balance))
                    continue
            # Throttle entry checks to every 3 bars for speed (entry on close still valid)
            setup = None
            if i % 3 == 0:
                key_levels = build_key_levels(lookback_15m, lookback_1m, now_est)
                swing_highs, swing_lows = swing_highs_lows(lookback_15m)
                trend = trend_from_structure(lookback_15m, swing_highs, swing_lows)
                setup = detect_setup(
                    lookback_1m, lookback_15m, key_levels, swing_highs, swing_lows, trend,
                    level_tolerance_pts=self.level_tolerance_pts,
                    require_trend_only=self.require_trend_only,
                    retest_only=self.retest_only,
                    min_body_pts=self.min_body_pts,
                )
            if setup is not None:
                trades_today = _trades_today_before(self.trades, now_est)
                mins_since_7 = (now_est.hour - 7) * 60 + now_est.minute if 7 <= now_est.hour < 12 else 0
                use_fallback = (
                    self.fallback_after_minutes > 0
                    and self.fallback_min_rr is not None
                    and trades_today == 0
                    and mins_since_7 >= self.fallback_after_minutes
                )
                effective_min_rr = self.fallback_min_rr if use_fallback else None
                self._try_open_trade(setup, now_est, lookback_1m, lookback_15m, effective_min_rr=effective_min_rr)

            if i % 20 == 0:
                self.equity_curve.append((now_est, self.balance))

        # Build result
        total_return = (self.balance - self.initial_balance) / self.initial_balance * 100
        winners = sum(1 for t in self.trades if t.pnl > 0)
        losers = sum(1 for t in self.trades if t.pnl <= 0)
        n = len(self.trades)
        win_rate = (100 * winners / n) if n else 0
        gross_profit = sum(t.pnl + t.partial_pnl for t in self.trades if t.pnl + t.partial_pnl > 0)
        gross_loss = abs(sum(t.pnl + t.partial_pnl for t in self.trades if t.pnl + t.partial_pnl < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0)
        avg_r = (sum(t.r_multiple for t in self.trades) / n) if n else 0

        equity = [e[1] for e in self.equity_curve]
        peak = self.initial_balance
        max_dd_usd = 0.0
        max_dd_pct = 0.0
        for b in equity:
            if b > peak:
                peak = b
            dd = peak - b
            if dd > max_dd_usd:
                max_dd_usd = dd
            dd_pct = (dd / peak * 100) if peak > 0 else 0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

        return BacktestResult(
            initial_balance=self.initial_balance,
            final_balance=self.balance,
            total_return_pct=total_return,
            total_trades=n,
            winners=winners,
            losers=losers,
            win_rate_pct=win_rate,
            max_drawdown_pct=max_dd_pct,
            max_drawdown_usd=max_dd_usd,
            profit_factor=profit_factor,
            avg_r_per_trade=avg_r,
            trades=self.trades,
            equity_curve=self.equity_curve,
        )
