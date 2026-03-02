"""
Telegram command handlers: /start, /stop, /status, /levels, /pnl, etc.
Uses HTML for a refined, scannable UI.
"""

from __future__ import annotations

import asyncio
import html
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters

from .alerts import format_trade_alert, format_trail_alert, send_telegram
from .scheduler import now_est
from config import (
    DEFAULT_CONTRACTS,
    INSTRUMENT,
    MAX_RISK_PER_TRADE_USD,
    MAX_TRADES_PER_DAY,
    TELEGRAM_CHAT_ID,
    TRAIL_ALERTS_ENABLED,
    TRAIL_MODE,
    USE_ORDERFLOW,
    AUTO_RETRAIN_ENABLED,
    RETRAIN_DAY_OF_WEEK,
    RETRAIN_HOUR_EST,
    RETRAIN_MINUTE_EST,
    BROKER,
    USE_LIVE_FEED,
    PRICE_API_URL,
    ORDERFLOW_API_URL,
    USE_ECONOMIC_CALENDAR,
)

logger = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")


def _esc(s: str) -> str:
    return html.escape(str(s), quote=False)


# Module-level state (risk/contracts persisted to BOT_STATE_JSON)
def _load_persisted_state():
    out = {}
    try:
        from config import BOT_STATE_JSON
        if BOT_STATE_JSON and BOT_STATE_JSON.exists():
            import json
            with open(BOT_STATE_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data.get("risk_per_trade"), (int, float)):
                out["risk_per_trade"] = max(1, min(500, float(data["risk_per_trade"])))
            if isinstance(data.get("contracts"), int):
                out["contracts"] = max(1, min(10, data["contracts"]))
            if "use_orderflow" in data:
                out["use_orderflow"] = bool(data["use_orderflow"])
    except Exception as e:
        logger.debug("Could not load bot_state.json: %s", e)
    return out

def _save_persisted_state():
    try:
        from config import BOT_STATE_JSON
        if not BOT_STATE_JSON:
            return
        BOT_STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
        import json
        with open(BOT_STATE_JSON, "w", encoding="utf-8") as f:
            json.dump({
                "risk_per_trade": _bot_state.get("risk_per_trade"),
                "contracts": _bot_state.get("contracts"),
                "use_orderflow": _bot_state.get("use_orderflow"),
            }, f, indent=0)
    except Exception as e:
        logger.warning("Could not save bot_state.json: %s", e)

_bot_state = {
    "scan_active": True,
    "trail_alerts": True,
    "trail_mode": "alert",
    "risk_per_trade": MAX_RISK_PER_TRADE_USD,
    "contracts": DEFAULT_CONTRACTS,
    "use_orderflow": False,  # default OFF; toggle with /orderflow on|off
    "session_premarket": True,
    "session_rth": True,
    "trades_today": 0,
    "daily_pnl": 0.0,
    "active_trades": [],
    "trade_history": [],
}
# Load persisted risk/contracts
for k, v in _load_persisted_state().items():
    _bot_state[k] = v

BOT_VERSION = "1.1.0"


def get_state():
    return _bot_state


def get_main_keyboard():
    """Reply keyboard for quick actions."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("▶ Start"), KeyboardButton("⏸ Pause")],
            [KeyboardButton("📊 Status"), KeyboardButton("📌 Levels")],
            [KeyboardButton("💰 Live Price"), KeyboardButton("📈 P&L")],
            [KeyboardButton("📋 History"), KeyboardButton("📊 Order flow"), KeyboardButton("🔌 APIs")],
            [KeyboardButton("❓ Help")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


async def _reply_html(update: Update, text: str, reply_markup=None) -> None:
    try:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
    except Exception:
        await update.message.reply_text(text, reply_markup=reply_markup)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _bot_state["scan_active"] = True
    await _reply_html(
        update,
        "<b>✅ MNQ Riley Coleman Bot</b>\n"
        "────────────────────\n"
        "Scanning <b>ON</b> • Session 7:00–11:00 AM EST\n\n"
        "Use buttons below or <code>/help</code> for commands.",
        reply_markup=get_main_keyboard(),
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _bot_state["scan_active"] = False
    await _reply_html(
        update,
        "⏸ <b>Scanning paused</b>\n\n"
        "Send <code>/start</code> to resume."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    active = _bot_state["active_trades"]
    scan = "Scanning" if _bot_state["scan_active"] else "Paused"
    lines = [
        "<b>📊 Status</b>",
        "────────────────────",
        f"Scan <b>{scan}</b>",
        f"Trades today <code>{_bot_state['trades_today']}</code> / {MAX_TRADES_PER_DAY}",
        f"Daily P&L <code>${_bot_state['daily_pnl']:+,.0f}</code>",
        f"Active trades <b>{len(active)}</b>",
    ]
    for t in active:
        d = t.get("direction", "?")
        e = t.get("entry", 0)
        s = t.get("stop", 0)
        lines.append(f"  • {d} @ <code>{e:,.2f}</code>  Stop <code>{s:,.2f}</code>")
    await _reply_html(update, "\n".join(lines))


def _get_apis_status_sync() -> list[str]:
    """Gather all API statuses (run in executor to avoid blocking). Returns list of HTML lines."""
    lines = ["<b>🔌 API Status</b>", "────────────────────"]
    try:
        from data import get_feed
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        feed_type = type(feed).__name__
        connected = feed.is_connected()
        delay_free = False
        if feed_type == "YahooWSFeed":
            ws = getattr(feed, "_ws", None)
            delay_free = bool(ws and ws.is_connected())
        elif feed_type in ("TradovateRealtimeFeed", "LocalAPIFeed"):
            delay_free = connected
        lines.append(f"<b>Price feed</b>  {feed_type}")
        lines.append(f"  Connected: <b>{'yes' if connected else 'no'}</b>")
        lines.append(f"  Delay-free: <b>{'yes' if delay_free else 'no'}</b>")
    except Exception as e:
        lines.append(f"<b>Price feed</b>  error: {_esc(str(e))}")
    lines.append("")
    try:
        of_url = (ORDERFLOW_API_URL or "").strip()
        if not of_url:
            lines.append("<b>Order flow</b>  not configured")
        else:
            lines.append(f"<b>Order flow</b>  <code>{_esc(of_url)}</code>")
            try:
                from main import _fetch_orderflow_summary
                summary = _fetch_orderflow_summary(timeout_sec=2)
                if summary is None:
                    lines.append("  Reachable: <b>no</b>")
                    lines.append("  Data: <b>no</b>")
                else:
                    lines.append("  Reachable: <b>yes</b>")
                    lines.append("  Data: <b>yes</b>")
                    src = summary.get("source", "?")
                    age = summary.get("age_seconds", "?")
                    lines.append(f"  Source: <b>{_esc(str(src))}</b>  Age: <code>{age}s</code>")
            except Exception as e:
                lines.append(f"  Reachable: <b>no</b> ({_esc(str(e)[:40])})")
    except Exception as e:
        lines.append(f"<b>Order flow</b>  error: {_esc(str(e))}")
    lines.append("")
    lines.append(f"<b>Economic calendar</b>  <b>{'on' if USE_ECONOMIC_CALENDAR else 'off'}</b>")
    return lines


async def cmd_apis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all APIs status (price feed, order flow, calendar)."""
    loop = asyncio.get_event_loop()
    lines = await loop.run_in_executor(None, _get_apis_status_sync)
    await _reply_html(update, "\n".join(lines))


async def cmd_levels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loop = asyncio.get_event_loop()
    levels_text, error_hint = await loop.run_in_executor(None, _fetch_levels_on_demand)
    if levels_text:
        await _reply_html(update, "<b>📌 Key Levels</b>\n────────────────────\n" + _esc(levels_text))
    else:
        price_line, feed_type = await loop.run_in_executor(None, _fetch_live_price_sync)
        msg = (
            "<b>📌 Key Levels</b>\n"
            "────────────────────\n"
            "Could not load levels.\n\n"
            f"<i>{_esc(error_hint)}</i>"
        )
        if price_line:
            msg += f"\n\n💰 <b>Live price</b> <code>{price_line}</code> (<i>{_esc(feed_type)}</i>)"
        msg += "\n\n• Tap <b>🔌 APIs</b> to check feed status.\n• US session: 7:00–11:00 AM EST."
        await _reply_html(update, msg)


def _fetch_levels_on_demand() -> tuple[str | None, str]:
    """Call main.get_levels_on_demand (sync, for executor). Returns (levels_text, error_hint)."""
    try:
        from main import get_levels_on_demand
        return get_levels_on_demand()
    except Exception as e:
        return None, str(e) or "Unknown error"


def _fetch_live_price_sync() -> tuple[str, str]:
    """Get live MNQ price and feed type (sync, for executor). Returns (price_line, feed_type)."""
    try:
        from data import get_feed
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        feed_type = type(feed).__name__
        if not feed.is_connected():
            return "", feed_type
        price = feed.get_current_price()
        if price is None:
            return "", feed_type
        return f"{price:,.2f}", feed_type
    except Exception as e:
        return "", str(e)


async def cmd_live_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show live MNQ price (button or /price)."""
    loop = asyncio.get_event_loop()
    price_line, feed_info = await loop.run_in_executor(None, _fetch_live_price_sync)
    if price_line:
        msg = (
            f"<b>💰 {INSTRUMENT} Live Price</b>\n"
            "────────────────────\n"
            f"<b><code>{price_line}</code></b>\n\n"
            f"<i>Source: {_esc(feed_info)}</i>"
        )
    else:
        msg = (
            f"<b>💰 {INSTRUMENT} Live Price</b>\n"
            "────────────────────\n"
            "Feed not connected or no price.\n\n"
            f"<i>Feed: {_esc(feed_info)}</i>\n"
            "Check <code>/apis</code> or start price server."
        )
    await _reply_html(update, msg)


async def cmd_pnl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    daily = _bot_state["daily_pnl"]
    weekly = _bot_state.get("weekly_pnl", daily)
    await _reply_html(
        update,
        "<b>📈 P&L Summary</b>\n"
        "────────────────────\n"
        f"Daily   <code>${daily:+,.0f}</code>\n"
        f"Weekly  <code>${weekly:+,.0f}</code>"
    )


async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args and context.args[0].replace(".", "").isdigit():
        amt = float(context.args[0])
        _bot_state["risk_per_trade"] = max(1, min(500, amt))
        _save_persisted_state()
        await _reply_html(
            update,
            f"✅ Max risk per trade set to <b>${_bot_state['risk_per_trade']:.0f}</b>"
        )
    else:
        await _reply_html(
            update,
            f"Current max risk: <code>${_bot_state['risk_per_trade']:.0f}</code>\n"
            "Usage: <code>/risk 380</code>"
        )


async def cmd_contracts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args and context.args[0].isdigit():
        n = int(context.args[0])
        _bot_state["contracts"] = max(1, min(10, n))
        _save_persisted_state()
        await _reply_html(update, f"✅ Contracts set to <b>{_bot_state['contracts']}</b>")
    else:
        await _reply_html(
            update,
            f"Contracts per trade: <b>{_bot_state['contracts']}</b>\n"
            "Usage: <code>/contracts 2</code>"
        )


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args and context.args[0].lower() in ("on", "off"):
        on = context.args[0].lower() == "on"
        _bot_state["session_premarket"] = on
        _bot_state["session_rth"] = on
        await _reply_html(
            update,
            f"Session scanning: <b>{'ON' if on else 'OFF'}</b>"
        )
    else:
        pre = "ON" if _bot_state["session_premarket"] else "OFF"
        await _reply_html(
            update,
            f"Session: <b>{pre}</b>\nUsage: <code>/session on</code> | <code>/session off</code>"
        )


async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    history = _bot_state.get("trade_history", [])[-10:]
    if not history:
        await _reply_html(update, "<i>No trade history yet.</i>")
        return
    lines = ["<b>📋 Last 10 trades</b>", "────────────────────"]
    for h in reversed(history):
        d = h.get("dir", "?")
        e = h.get("entry", 0)
        res = h.get("result", "")
        pnl = h.get("pnl", 0)
        lines.append(f"• {d} @ <code>{e:,.2f}</code> → {res} <code>${pnl:+.0f}</code>")
    await _reply_html(update, "\n".join(lines))


async def cmd_trail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args and context.args[0].lower() in ("on", "off"):
        _bot_state["trail_alerts"] = context.args[0].lower() == "on"
        await _reply_html(
            update,
            f"Trailing alerts: <b>{'ON' if _bot_state['trail_alerts'] else 'OFF'}</b>"
        )
    else:
        on = "ON" if _bot_state["trail_alerts"] else "OFF"
        await _reply_html(
            update,
            f"Trailing alerts: <b>{on}</b>\nUsage: <code>/trail on</code> | <code>/trail off</code>"
        )


async def cmd_trailmode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args and context.args[0].lower() in ("auto", "alert"):
        _bot_state["trail_mode"] = context.args[0].lower()
        await _reply_html(
            update,
            f"Trail mode: <b>{_bot_state['trail_mode']}</b> "
            "(auto-move stop vs alert-only)"
        )
    else:
        await _reply_html(
            update,
            f"Trail mode: <b>{_bot_state['trail_mode']}</b>\n"
            "Usage: <code>/trailmode auto</code> | <code>/trailmode alert</code>"
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_html(
        update,
        "<b>🤖 MNQ Riley Coleman Bot</b>\n"
        "────────────────────\n\n"
        "<b>Control</b>\n"
        "<code>/start</code> – Start scanning\n"
        "<code>/stop</code> – Pause scanning\n"
        "<code>/help</code> – This message\n\n"
        "<b>Info</b>\n"
        "<code>/status</code> – Scan state, trades, P&L\n"
        "<code>/levels</code> – Today's key levels\n"
        "<code>/price</code> – Live MNQ price\n"
        "<code>/pnl</code> – Daily/weekly P&L\n"
        "<code>/stats</code> – Win rate, total P&L\n"
        "<code>/weekly</code> – 7-day P&L\n"
        "<code>/monthly</code> – 30-day P&L\n"
        "<code>/history</code> – Last 10 trades\n"
        "<code>/orderflow</code> – Order flow status\n"
        "<code>/demo signal</code> – Demo trade alert\n"
        "<code>/demo trail</code> – Demo trail alert\n"
        "<code>/demo levels</code> – Demo key levels\n"
        "📊 <b>Order flow</b> – Toggle order flow in strategy ON/OFF\n"
        "🔌 <b>APIs</b> – All APIs status (price, order flow, calendar)\n\n"
        "<b>Settings</b>\n"
        "<code>/config</code> – Current settings\n"
        "<code>/risk [amount]</code> – Max $ per trade\n"
        "<code>/contracts [n]</code> – MNQ contracts\n"
        "<code>/session on|off</code> – Session scan\n"
        "<code>/trail on|off</code> – Trail alerts\n"
        "<code>/trailmode auto|alert</code> – Trail behavior\n\n"
        "<code>/nextretrain</code> – Next auto-retrain time\n"
        "<code>/version</code> – Bot version\n"
        "<code>/backtest [days]</code> – Run short backtest (default 2 days)"
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Win rate, total trades, total P&L from trade history."""
    history = _bot_state.get("trade_history", [])
    if not history:
        await _reply_html(update, "<b>📊 Stats</b>\n────────────────────\n<i>No trades yet.</i>")
        return
    winners = sum(1 for h in history if (h.get("pnl") or 0) > 0)
    losers = len(history) - winners
    total_pnl = sum(h.get("pnl", 0) for h in history)
    wr = (100 * winners / len(history)) if history else 0
    await _reply_html(
        update,
        "<b>📊 Stats</b>\n"
        "────────────────────\n"
        f"Trades <b>{len(history)}</b>  │  ✅ {winners}  │  ❌ {losers}\n"
        f"Win rate <b>{wr:.0f}%</b>\n"
        f"Total P&L <code>${total_pnl:+,.0f}</code>"
    )


def _effective_use_orderflow() -> bool:
    """Order flow in strategy: from bot state if set, else config."""
    if "use_orderflow" in _bot_state:
        return bool(_bot_state["use_orderflow"])
    return USE_ORDERFLOW


async def cmd_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current bot config (risk, contracts, session, trail, order flow)."""
    session = "ON" if _bot_state.get("session_premarket", True) else "OFF"
    trail = "ON" if _bot_state.get("trail_alerts", True) else "OFF"
    of = "ON" if _effective_use_orderflow() else "OFF"
    await _reply_html(
        update,
        "<b>⚙️ Config</b>\n"
        "────────────────────\n"
        f"Risk/trade <code>${_bot_state.get('risk_per_trade', 0):.0f}</code>\n"
        f"Contracts <code>{_bot_state.get('contracts', 1)}</code>\n"
        f"Session scan <b>{session}</b>\n"
        f"Trail alerts <b>{trail}</b>\n"
        f"Trail mode <b>{_bot_state.get('trail_mode', 'alert')}</b>\n"
        f"Order flow <b>{of}</b>\n\n"
        "<i>Tap 📊 Order flow to toggle.</i>"
    )


async def cmd_orderflow_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle order flow in strategy on/off; persist and confirm."""
    from config import ORDERFLOW_API_URL
    current = _effective_use_orderflow()
    new_value = not current
    _bot_state["use_orderflow"] = new_value
    _save_persisted_state()
    label = "ON" if new_value else "OFF"
    if new_value and not ORDERFLOW_API_URL:
        await _reply_html(
            update,
            f"<b>📊 Order flow</b>\n"
            f"────────────────────\n"
            f"Strategy: <b>{label}</b>\n\n"
            f"<i>Set MNQ_ORDERFLOW_API_URL and run the order flow server for live data.</i>"
        )
        return
    await _reply_html(
        update,
        f"<b>📊 Order flow</b>\n"
        f"────────────────────\n"
        f"Strategy: <b>{label}</b>\n\n"
        f"Entries {'require' if new_value else 'do not require'} order flow confirmation."
    )


async def cmd_orderflow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Order flow status: on/off and last summary if available."""
    from config import ORDERFLOW_API_URL
    effective = _effective_use_orderflow()
    if not effective:
        await _reply_html(
            update,
            "<b>📊 Order flow</b>\n"
            "────────────────────\n"
            "Strategy: <b>OFF</b> (entries do not require order flow).\n\n"
            "Tap <b>📊 Order flow</b> to turn ON, or set <code>MNQ_USE_ORDERFLOW=true</code> and restart."
        )
        return
    summary = _bot_state.get("last_orderflow_summary")
    if not summary:
        await _reply_html(
            update,
            "<b>📊 Order flow</b>\n"
            "────────────────────\n"
            f"<b>ON</b>  │  API <code>{_esc(ORDERFLOW_API_URL or '')}</code>\n"
            "<i>No summary yet this session.</i>"
        )
        return
    age = summary.get("age_seconds", 0)
    imb = summary.get("imbalance_ratio", 0)
    await _reply_html(
        update,
        "<b>📊 Order flow</b>\n"
        "────────────────────\n"
        f"<b>ON</b>  │  Age <code>{age:.0f}s</code>  │  Imbalance <code>{imb:.3f}</code>"
    )


async def cmd_version(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_html(
        update,
        f"<b>MNQ Riley Coleman Bot</b> v{BOT_VERSION}\n"
        "────────────────────\n"
        "<i>Riley Coleman price-action strategy • MNQ</i>"
    )


async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """P&L and stats for last 7 days."""
    from datetime import timedelta
    history = _bot_state.get("trade_history", [])
    cutoff = (datetime.now(EST) - timedelta(days=7)).strftime("%Y-%m-%d")
    week_trades = [h for h in history if (h.get("date") or "") >= cutoff]
    if not week_trades:
        await _reply_html(update, "<b>📅 Weekly</b>\n────────────────────\n<i>No trades in last 7 days.</i>")
        return
    winners = sum(1 for h in week_trades if (h.get("pnl") or 0) > 0)
    total = sum(h.get("pnl", 0) for h in week_trades)
    wr = (100 * winners / len(week_trades)) if week_trades else 0
    await _reply_html(
        update,
        "<b>📅 Weekly (7 days)</b>\n"
        "────────────────────\n"
        f"Trades <b>{len(week_trades)}</b>  │  Win rate <b>{wr:.0f}%</b>\n"
        f"P&L <code>${total:+,.0f}</code>"
    )


async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """P&L and stats for last 30 days."""
    from datetime import timedelta
    history = _bot_state.get("trade_history", [])
    cutoff = (datetime.now(EST) - timedelta(days=30)).strftime("%Y-%m-%d")
    month_trades = [h for h in history if (h.get("date") or "") >= cutoff]
    if not month_trades:
        await _reply_html(update, "<b>📆 Monthly</b>\n────────────────────\n<i>No trades in last 30 days.</i>")
        return
    winners = sum(1 for h in month_trades if (h.get("pnl") or 0) > 0)
    total = sum(h.get("pnl", 0) for h in month_trades)
    wr = (100 * winners / len(month_trades)) if month_trades else 0
    await _reply_html(
        update,
        "<b>📆 Monthly (30 days)</b>\n"
        "────────────────────\n"
        f"Trades <b>{len(month_trades)}</b>  │  Win rate <b>{wr:.0f}%</b>\n"
        f"P&L <code>${total:+,.0f}</code>"
    )


async def cmd_nextretrain(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Next scheduled auto-retrain (EST)."""
    if not AUTO_RETRAIN_ENABLED:
        await _reply_html(update, "<b>🔄 Next retrain</b>\n────────────────────\n<i>Auto-retrain is disabled.</i>")
        return
    # Config: 0=Sunday, 1=Monday, ... 6=Saturday. Python weekday(): Monday=0, Sunday=6.
    from datetime import timedelta
    now = datetime.now(EST)
    python_target = 6 if RETRAIN_DAY_OF_WEEK == 0 else RETRAIN_DAY_OF_WEEK - 1
    days_ahead = (python_target - now.weekday()) % 7
    if days_ahead == 0 and (now.hour > RETRAIN_HOUR_EST or (now.hour == RETRAIN_HOUR_EST and now.minute >= RETRAIN_MINUTE_EST)):
        days_ahead = 7
    next_date = (now + timedelta(days=days_ahead)).replace(hour=RETRAIN_HOUR_EST, minute=RETRAIN_MINUTE_EST, second=0, microsecond=0)
    await _reply_html(
        update,
        "<b>🔄 Next retrain</b>\n"
        "────────────────────\n"
        f"<code>{next_date.strftime('%A %Y-%m-%d %H:%M')} EST</code>\n\n"
        "<i>Restart bot after retrain to apply new params.</i>"
    )


def _run_backtest_sync(days: int = 2, risk: int = 380) -> str:
    """Run backtest in subprocess; return report text (or error). Blocking."""
    root = Path(__file__).resolve().parent.parent
    exe = sys.executable
    cmd = [exe, str(root / "run_backtest.py"), "--days", str(days), "--balance", "50000", "--risk", str(risk)]
    try:
        r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")
        if not out.strip():
            return "Backtest produced no output."
        lines = out.strip().split("\n")
        for i in range(len(lines) - 1, -1, -1):
            if "BACKTEST REPORT" in lines[i] or "Net P&L" in lines[i]:
                report = "\n".join(lines[i:])
                return report[:4000] if len(report) > 4000 else report
        return out[-3000:] if len(out) > 3000 else out
    except subprocess.TimeoutExpired:
        return "Backtest timed out (120s). Try fewer days."
    except Exception as e:
        return f"Backtest error: {e}"


async def cmd_backtest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run short backtest (default 2 days) and send report."""
    days = 2
    risk = int(_bot_state.get("risk_per_trade", 380))
    if context.args and context.args[0].isdigit():
        days = max(1, min(14, int(context.args[0])))
    await _reply_html(update, f"<b>⏳ Running backtest</b> ({days} days, risk ${risk})…")
    loop = asyncio.get_event_loop()
    report = await loop.run_in_executor(None, _run_backtest_sync, days, risk)
    await _reply_html(update, "<b>📊 Backtest</b>\n<pre>" + _esc(report) + "</pre>")


async def handle_keyboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route button text to the right command."""
    text = (update.message and update.message.text or "").strip()
    if text == "▶ Start":
        await cmd_start(update, context)
    elif text == "⏸ Pause":
        await cmd_stop(update, context)
    elif text == "📊 Status":
        await cmd_status(update, context)
    elif text == "📌 Levels":
        await cmd_levels(update, context)
    elif text == "📈 P&L":
        await cmd_pnl(update, context)
    elif text == "📋 History":
        await cmd_history(update, context)
    elif text == "📊 Order flow":
        await cmd_orderflow_toggle(update, context)
    elif text == "💰 Live Price":
        await cmd_live_price(update, context)
    elif text == "🔌 APIs":
        await cmd_apis(update, context)
    elif text == "❓ Help":
        await cmd_help(update, context)


async def cmd_demo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /demo [signal|trail|levels] – send demo alerts."""
    if context.args:
        arg = context.args[0].lower()
        if arg == "signal":
            await cmd_demo_signal(update, context)
            return
        if arg == "trail":
            await cmd_demo_trail(update, context)
            return
        if arg == "levels":
            await cmd_demo_levels(update, context)
            return
    await _reply_html(
        update,
        "<b>Demo commands</b>\n"
        "<code>/demo signal</code> – demo trade alert\n"
        "<code>/demo trail</code> – demo trail stop alert\n"
        "<code>/demo levels</code> – demo key levels"
    )


async def cmd_demo_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a demo trade alert to the configured chat (no real trade)."""
    if not TELEGRAM_CHAT_ID:
        await _reply_html(update, "❌ No <code>TELEGRAM_CHAT_ID</code> set.")
        return
    time_est = now_est().strftime("%I:%M %p EST")
    msg = format_trade_alert(
        setup_name="Retest Reversal",
        time_est=time_est,
        direction="LONG",
        entry=21500.25,
        stop=21480.50,
        tp1=21540.00,
        tp2=21580.00,
        rr_ratio=2.0,
        confidence="High",
        timeframe_note="1-min | 15-min trend: Bullish",
        key_level="7 AM High",
        notes="Demo signal – not a real trade.",
    )
    ok = await send_telegram(msg, context.bot, TELEGRAM_CHAT_ID)
    if ok:
        await _reply_html(update, "✅ Demo signal sent to your chat.")
    else:
        await _reply_html(update, "❌ Failed to send demo signal.")


async def cmd_demo_trail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a demo trail-stop alert (no real trade)."""
    if not TELEGRAM_CHAT_ID:
        await _reply_html(update, "❌ No <code>TELEGRAM_CHAT_ID</code> set.")
        return
    msg = format_trail_alert(
        direction="LONG",
        entry=21500.25,
        current_price=21530.00,
        floating_r=1.5,
        action="Move Stop Loss to +1R",
        new_stop=21520.00,
        locked_comment="(locks in +$40/contract)",
        target2=21580.00,
        tip="Take 50% off here and let the rest run!",
    )
    ok = await send_telegram(msg, context.bot, TELEGRAM_CHAT_ID)
    if ok:
        await _reply_html(update, "✅ Demo trail alert sent to your chat.")
    else:
        await _reply_html(update, "❌ Failed to send demo trail alert.")


async def cmd_demo_levels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a demo key levels message (sample values)."""
    if not TELEGRAM_CHAT_ID:
        await _reply_html(update, "❌ No <code>TELEGRAM_CHAT_ID</code> set.")
        return
    msg = (
        "<b>📌 Today's Key Levels</b> <i>(demo)</i>\n"
        "────────────────────\n"
        "Prev Day H: 21,485.50\n"
        "Prev Day L: 21,420.25\n"
        "Prev Day C: 21,455.00\n"
        "7 AM H: 21,472.00\n"
        "7 AM L: 21,438.00\n"
        "Session OR H: 21,468.00\n"
        "Session OR L: 21,442.00"
    )
    ok = await send_telegram(msg, context.bot, TELEGRAM_CHAT_ID)
    if ok:
        await _reply_html(update, "✅ Demo levels sent to your chat.")
    else:
        await _reply_html(update, "❌ Failed to send demo levels.")


def register_commands(application):
    """Register all command handlers and keyboard button handler."""
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("levels", cmd_levels))
    application.add_handler(CommandHandler("price", cmd_live_price))
    application.add_handler(CommandHandler("pnl", cmd_pnl))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("config", cmd_config))
    application.add_handler(CommandHandler("orderflow", cmd_orderflow))
    application.add_handler(CommandHandler("apis", cmd_apis))
    application.add_handler(CommandHandler("nextretrain", cmd_nextretrain))
    application.add_handler(CommandHandler("version", cmd_version))
    application.add_handler(CommandHandler("weekly", cmd_weekly))
    application.add_handler(CommandHandler("monthly", cmd_monthly))
    application.add_handler(CommandHandler("backtest", cmd_backtest))
    application.add_handler(CommandHandler("risk", cmd_risk))
    application.add_handler(CommandHandler("contracts", cmd_contracts))
    application.add_handler(CommandHandler("session", cmd_session))
    application.add_handler(CommandHandler("history", cmd_history))
    application.add_handler(CommandHandler("trail", cmd_trail))
    application.add_handler(CommandHandler("trailmode", cmd_trailmode))
    application.add_handler(CommandHandler("demo", cmd_demo))
    application.add_handler(CommandHandler("demo_signal", cmd_demo_signal))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("pause", cmd_stop))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyboard_button))