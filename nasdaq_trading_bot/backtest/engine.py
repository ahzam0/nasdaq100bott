"""
Backtest engine: vectorized with NASDAQ cost model (commission, SEC, FINRA, slippage, PDT).
Produces equity curve and trades for metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: pd.DataFrame
    initial_balance: float
    final_balance: float
    metrics: Optional[Any] = None
    exit_reasons: Optional[list] = None  # "signal" | "hit" | "trail" per trade


class BacktestEngine:
    """
    Run strategy signals through NASDAQ cost model.
    Strategy provides entries/exits; engine applies costs and builds equity.
    """

    def __init__(
        self,
        initial_balance: float = 50_000.0,
        commission_per_dollar: float = 0.0,
        sec_fee_per_dollar_sold: float = 0.0000278,
        finra_taf_per_share: float = 0.000166,
        finra_taf_max: float = 8.30,
        slippage_bps: float = 5.0,
        pdt_max_trades: int = 3,
        pdt_lookback_days: int = 5,
    ):
        self.initial_balance = initial_balance
        self.commission_per_dollar = commission_per_dollar
        self.sec_fee_per_dollar_sold = sec_fee_per_dollar_sold
        self.finra_taf_per_share = finra_taf_per_share
        self.finra_taf_max = finra_taf_max
        self.slippage_bps = slippage_bps
        self.pdt_max_trades = pdt_max_trades
        self.pdt_lookback_days = pdt_lookback_days

    def run(
        self,
        prices: pd.Series,
        signals: pd.Series,
        size: Optional[pd.Series] = None,
        benchmark_returns: Optional[pd.Series] = None,
    ) -> BacktestResult:
        """
        prices: close price series (aligned with signals)
        signals: 1 = long, -1 = short, 0 = flat
        size: optional position size (shares or fraction of equity); default 1
        """
        if prices is None or prices.empty or signals is None or signals.empty:
            return BacktestResult(
                equity_curve=pd.Series([self.initial_balance]),
                trades=pd.DataFrame(),
                initial_balance=self.initial_balance,
                final_balance=self.initial_balance,
            )
        # Align
        idx = prices.index.union(signals.index).drop_duplicates().sort_values()
        prices = prices.reindex(idx).ffill().bfill()
        signals = signals.reindex(idx).ffill().fillna(0)
        if size is None:
            size = pd.Series(1.0, index=idx)
        else:
            size = size.reindex(idx).ffill().fillna(1.0)

        n = len(idx)
        equity = np.full(n, self.initial_balance, dtype=float)
        position = 0.0
        entry_price = 0.0
        trades = []

        for i in range(1, n):
            prev_sig = int(signals.iloc[i - 1]) if not pd.isna(signals.iloc[i - 1]) else 0
            curr_sig = int(signals.iloc[i]) if not pd.isna(signals.iloc[i]) else 0
            price = float(prices.iloc[i])
            sz = float(size.iloc[i]) if size is not None else 1.0

            # Close position on signal change
            if position != 0 and (curr_sig == 0 or (curr_sig * position < 0)):
                exit_price = price * (1 - self.slippage_bps / 10000.0) if position > 0 else price * (1 + self.slippage_bps / 10000.0)
                pnl = position * (exit_price - entry_price)
                # Costs
                notional = abs(position * exit_price)
                sec_fee = notional * self.sec_fee_per_dollar_sold
                finra = min(self.finra_taf_max, abs(position) * self.finra_taf_per_share)
                pnl -= sec_fee + finra
                equity[i] = equity[i - 1] + pnl
                trades.append({"entry_time": idx[i - 1], "exit_time": idx[i], "pnl": pnl, "position": position, "entry_price": entry_price, "exit_price": exit_price})
                position = 0.0
            else:
                equity[i] = equity[i - 1]

            # Open new position
            if curr_sig != 0 and position == 0:
                entry_price = price * (1 + self.slippage_bps / 10000.0) if curr_sig > 0 else price * (1 - self.slippage_bps / 10000.0)
                position = curr_sig * sz
                equity[i] = equity[i - 1]

        if position != 0:
            # Mark to market at last price
            last_price = float(prices.iloc[-1])
            pnl = position * (last_price - entry_price)
            equity[-1] = equity[-2] + pnl
            trades.append({"entry_time": idx[-2], "exit_time": idx[-1], "pnl": pnl, "position": position, "entry_price": entry_price, "exit_price": last_price})

        equity_curve = pd.Series(equity, index=idx)
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["entry_time", "exit_time", "pnl", "position", "entry_price", "exit_price"])
        final = float(equity_curve.iloc[-1]) if not equity_curve.empty else self.initial_balance

        from backtest.metrics import compute_metrics
        ret = equity_curve.pct_change().dropna()
        m = compute_metrics(
            ret,
            equity_curve,
            trades_df,
            benchmark_returns=benchmark_returns.reindex(idx).ffill().pct_change().dropna() if benchmark_returns is not None else None,
            initial_balance=self.initial_balance,
        )

        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades_df,
            initial_balance=self.initial_balance,
            final_balance=final,
            metrics=m,
        )

    def run_hit_and_trail(
        self,
        df: pd.DataFrame,
        signals: pd.Series,
        take_profit_pct: float = 0.02,
        trailing_stop_pct: float = 0.01,
        size: Optional[pd.Series] = None,
        benchmark_returns: Optional[pd.Series] = None,
        eod_exit: bool = False,
    ) -> BacktestResult:
        """
        Run backtest with hit (take-profit) and trail (trailing-stop) exits.
        df: must have columns high, low, close (and index).
        take_profit_pct: e.g. 0.02 = 2% profit target (hit).
        trailing_stop_pct: e.g. 0.01 = 1% trail from extreme (trail).
        Exits: hit checked first, then trail. Then signal flip.
        """
        if df is None or df.empty or "high" not in df.columns or "low" not in df.columns or "close" not in df.columns:
            return BacktestResult(
                equity_curve=pd.Series([self.initial_balance]),
                trades=pd.DataFrame(),
                initial_balance=self.initial_balance,
                final_balance=self.initial_balance,
            )
        idx = df.index.union(signals.index).drop_duplicates().sort_values()
        df = df.reindex(idx).ffill().bfill()
        prices = df["close"]
        high = df["high"]
        low = df["low"]
        signals = signals.reindex(idx).ffill().fillna(0)
        if size is None:
            size = pd.Series(1.0, index=idx)
        else:
            size = size.reindex(idx).ffill().fillna(1.0)

        n = len(idx)
        try:
            is_last_of_day = (pd.Series(idx).dt.normalize().shift(-1) != pd.Series(idx).dt.normalize()).values
            is_last_of_day[-1] = True
        except Exception:
            is_last_of_day = np.zeros(n, dtype=bool)
            is_last_of_day[-1] = True

        equity = np.full(n, self.initial_balance, dtype=float)
        position = 0.0
        entry_price = 0.0
        running_high = 0.0
        running_low = np.inf
        trades = []
        exit_reasons = []

        for i in range(1, n):
            curr_sig = int(signals.iloc[i]) if not pd.isna(signals.iloc[i]) else 0
            h = float(high.iloc[i])
            l = float(low.iloc[i])
            price = float(prices.iloc[i])
            sz = float(size.iloc[i])

            exit_price = None
            reason = None

            if eod_exit and position != 0 and is_last_of_day[i]:
                exit_price = price * (1 - self.slippage_bps / 10000.0) if position > 0 else price * (1 + self.slippage_bps / 10000.0)
                reason = "eod"

            if position > 0 and exit_price is None:
                running_high = max(running_high, h)
                if h >= entry_price * (1.0 + take_profit_pct):
                    exit_price = entry_price * (1.0 + take_profit_pct)
                    reason = "hit"
                elif running_high > 0 and l <= running_high * (1.0 - trailing_stop_pct):
                    exit_price = running_high * (1.0 - trailing_stop_pct)
                    reason = "trail"
                elif curr_sig <= 0:
                    exit_price = price * (1 - self.slippage_bps / 10000.0)
                    reason = "signal"
            elif position < 0 and exit_price is None:
                running_low = min(running_low, l) if running_low < 1e30 else l
                if l <= entry_price * (1.0 - take_profit_pct):
                    exit_price = entry_price * (1.0 - take_profit_pct)
                    reason = "hit"
                elif running_low < 1e30 and h >= running_low * (1.0 + trailing_stop_pct):
                    exit_price = running_low * (1.0 + trailing_stop_pct)
                    reason = "trail"
                elif curr_sig >= 0:
                    exit_price = price * (1 + self.slippage_bps / 10000.0)
                    reason = "signal"

            if exit_price is not None and reason:
                pnl = position * (exit_price - entry_price)
                notional = abs(position * exit_price)
                sec_fee = notional * self.sec_fee_per_dollar_sold
                finra = min(self.finra_taf_max, abs(position) * self.finra_taf_per_share)
                pnl -= sec_fee + finra
                equity[i] = equity[i - 1] + pnl
                trades.append({"entry_time": idx[i - 1], "exit_time": idx[i], "pnl": pnl, "position": position, "entry_price": entry_price, "exit_price": exit_price, "exit_reason": reason})
                exit_reasons.append(reason)
                position = 0.0
                running_high = 0.0
                running_low = np.inf
            else:
                equity[i] = equity[i - 1]

            if position == 0 and curr_sig != 0:
                entry_price = price * (1 + self.slippage_bps / 10000.0) if curr_sig > 0 else price * (1 - self.slippage_bps / 10000.0)
                position = curr_sig * sz
                running_high = float(high.iloc[i]) if curr_sig > 0 else 0.0
                running_low = float(low.iloc[i]) if curr_sig < 0 else np.inf

        if position != 0:
            last_price = float(prices.iloc[-1])
            pnl = position * (last_price - entry_price)
            equity[-1] = equity[-2] + pnl
            trades.append({"entry_time": idx[-2], "exit_time": idx[-1], "pnl": pnl, "position": position, "entry_price": entry_price, "exit_price": last_price, "exit_reason": "signal"})
            exit_reasons.append("signal")

        equity_curve = pd.Series(equity, index=idx)
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["entry_time", "exit_time", "pnl", "position", "entry_price", "exit_price", "exit_reason"])
        final = float(equity_curve.iloc[-1]) if not equity_curve.empty else self.initial_balance

        from backtest.metrics import compute_metrics
        ret = equity_curve.pct_change().dropna()
        m = compute_metrics(
            ret,
            equity_curve,
            trades_df,
            benchmark_returns=benchmark_returns.reindex(idx).ffill().pct_change().dropna() if benchmark_returns is not None else None,
            initial_balance=self.initial_balance,
        )
        return BacktestResult(
            equity_curve=equity_curve,
            trades=trades_df,
            initial_balance=self.initial_balance,
            final_balance=final,
            metrics=m,
            exit_reasons=exit_reasons,
        )
