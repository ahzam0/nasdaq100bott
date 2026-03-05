"""
Equity curve tracker for MNQ trading bot.
Stores snapshots in JSON and provides stats/chart generation.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend for PNG export
import matplotlib.pyplot as plt
import numpy as np

# Use same data dir as trade_data.json so path is identical across bot/dashboard
try:
    from config import DATA_DIR as _DATA_DIR
except ImportError:
    _DATA_DIR = Path(__file__).resolve().parent
EQUITY_CURVE_PATH = _DATA_DIR / "equity_curve.json"

# Default initial balance (from config or strategy reference)
DEFAULT_INITIAL_BALANCE = 50_000.0


def _load_snapshots() -> list[dict]:
    """Load snapshots from JSON file. Returns empty list if file missing or invalid."""
    if not EQUITY_CURVE_PATH.exists():
        return []
    try:
        data = json.loads(EQUITY_CURVE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "snapshots" in data:
            return data["snapshots"]
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _save_snapshots(snapshots: list[dict]) -> None:
    """Write snapshots to JSON file."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    EQUITY_CURVE_PATH.write_text(
        json.dumps(snapshots, indent=2),
        encoding="utf-8",
    )


def _get_initial_balance() -> float:
    """Get initial balance from config or default."""
    try:
        runtime_path = _DATA_DIR / "runtime_settings.json"
        if runtime_path.exists():
            data = json.loads(runtime_path.read_text(encoding="utf-8"))
            if "initial_balance" in data:
                return float(data["initial_balance"])
    except Exception:
        pass
    return DEFAULT_INITIAL_BALANCE


def record_equity(balance: float, pnl: float, trade_count: int) -> None:
    """Append an equity snapshot with current timestamp."""
    snapshot = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "balance": float(balance),
        "pnl": float(pnl),
        "trade_count": int(trade_count),
    }
    snapshots = _load_snapshots()
    snapshots.append(snapshot)
    _save_snapshots(snapshots)


def get_equity_curve() -> list[dict]:
    """Return all equity snapshots."""
    return _load_snapshots()


def reset_equity_curve() -> bool:
    """Clear all equity snapshots (e.g. when user runs /reset confirm). Returns True if ok.
    Overwrites file in place (no unlink) so other processes (e.g. dashboard) see new content."""
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        EQUITY_CURVE_PATH.write_text("[]", encoding="utf-8")
        return True
    except Exception:
        return False


def get_equity_stats() -> dict:
    """
    Return stats: peak_balance, current_balance, max_drawdown_usd, max_drawdown_pct,
    total_return_pct, sharpe_estimate.
    Handles empty data gracefully.
    """
    snapshots = _load_snapshots()
    initial = _get_initial_balance()

    if not snapshots:
        return {
            "peak_balance": initial,
            "current_balance": initial,
            "max_drawdown_usd": 0.0,
            "max_drawdown_pct": 0.0,
            "total_return_pct": 0.0,
            "sharpe_estimate": 0.0,
        }

    balances = [s["balance"] for s in snapshots]
    current = balances[-1]
    peak = max(balances)

    # Initial balance: first snapshot or config default
    first_balance = balances[0]
    initial_for_return = initial if initial > 0 else first_balance

    # Max drawdown (USD and %)
    running_peak = balances[0]
    max_dd_usd = 0.0
    for b in balances:
        running_peak = max(running_peak, b)
        dd = running_peak - b
        if dd > max_dd_usd:
            max_dd_usd = dd

    max_dd_pct = (max_dd_usd / running_peak * 100) if running_peak > 0 else 0.0

    # Total return %
    total_return_pct = (
        ((current - initial_for_return) / initial_for_return * 100)
        if initial_for_return > 0
        else 0.0
    )

    # Sharpe estimate: annualized from daily returns (252 trading days)
    sharpe_estimate = 0.0
    if len(balances) >= 2:
        returns = np.diff(np.array(balances, dtype=float)) / np.array(balances[:-1], dtype=float)
        returns = returns[~np.isnan(returns)]
        if len(returns) > 0 and np.std(returns) > 0:
            # Assume snapshots are roughly daily; annualize
            mean_ret = np.mean(returns)
            std_ret = np.std(returns)
            sharpe_estimate = float(mean_ret / std_ret * np.sqrt(252))

    return {
        "peak_balance": peak,
        "current_balance": current,
        "max_drawdown_usd": round(max_dd_usd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "total_return_pct": round(total_return_pct, 2),
        "sharpe_estimate": round(sharpe_estimate, 2),
    }


def generate_equity_chart() -> bytes:
    """
    Generate a PNG chart: equity curve (blue), drawdown area (red fill below peak).
    Returns PNG bytes for sending via Telegram.
    """
    snapshots = _load_snapshots()
    initial = _get_initial_balance()

    fig, ax = plt.subplots(figsize=(10, 5))

    if not snapshots:
        ax.text(0.5, 0.5, "No equity data yet", ha="center", va="center", fontsize=14)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
    else:
        timestamps = [s["timestamp"] for s in snapshots]
        balances = np.array([s["balance"] for s in snapshots], dtype=float)

        # X-axis: use indices or parse timestamps for nicer labels
        x = np.arange(len(timestamps))
        ax.plot(x, balances, color="blue", linewidth=2, label="Equity")

        # Running peak and drawdown area
        running_peak = np.maximum.accumulate(balances)
        ax.fill_between(x, running_peak, balances, color="red", alpha=0.3, label="Drawdown")

        # Tick labels: show subset of timestamps to avoid crowding
        step = max(1, len(timestamps) // 8)
        tick_indices = list(range(0, len(timestamps), step))
        if tick_indices[-1] != len(timestamps) - 1:
            tick_indices.append(len(timestamps) - 1)
        ax.set_xticks([x[i] for i in tick_indices])
        ax.set_xticklabels(
            [timestamps[i][:10] if len(timestamps[i]) >= 10 else timestamps[i] for i in tick_indices],
            rotation=45,
            ha="right",
        )

        ax.axhline(y=initial, color="gray", linestyle="--", alpha=0.6, label=f"Initial (${initial:,.0f})")

    ax.set_title("MNQ Bot – Equity Curve")
    ax.set_xlabel("Time")
    ax.set_ylabel("Balance ($)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8)

    plt.tight_layout()

    buf = __import__("io").BytesIO()
    fig.savefig(buf, format="PNG", dpi=100, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
