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

from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from .alerts import format_trade_alert, format_trail_alert, send_telegram, send_telegram_all, send_photo_all, format_weekly_report
from .scheduler import now_est
from config import (
    DEFAULT_CONTRACTS,
    INSTRUMENT,
    MAX_RISK_PER_TRADE_USD,
    MAX_TRADES_PER_DAY,
    TELEGRAM_CHAT_ID,
    TELEGRAM_CHAT_IDS,
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
    TRADE_DATA_JSON,
    get_use_yahoo_ws_realtime,
    set_use_yahoo_ws_realtime,
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


def _load_trade_data():
    """Load trade_history, active_trades, daily_pnl, trades_today from trade_data.json."""
    out = {}
    try:
        if not TRADE_DATA_JSON or not TRADE_DATA_JSON.exists():
            return out
        import json
        from strategy.trade_manager import active_trade_from_dict
        with open(TRADE_DATA_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("trade_history"), list):
            out["trade_history"] = data["trade_history"]
        if isinstance(data.get("daily_pnl"), (int, float)):
            out["daily_pnl"] = float(data["daily_pnl"])
        if isinstance(data.get("trades_today"), int):
            out["trades_today"] = max(0, data["trades_today"])
        if isinstance(data.get("last_trade_date"), str):
            out["last_trade_date"] = data["last_trade_date"]
        if isinstance(data.get("active_trades"), list):
            restored = []
            for i, item in enumerate(data["active_trades"]):
                if not isinstance(item, dict):
                    continue
                trade_dict = item.get("trade") if "trade" in item else item
                if not isinstance(trade_dict, dict):
                    continue
                try:
                    trade = active_trade_from_dict(trade_dict)
                    restored.append({
                        "trade": trade,
                        "id": item.get("id", i + 1),
                        "direction": trade.direction,
                        "entry": trade.entry,
                        "stop": trade.current_stop,
                    })
                except Exception as e:
                    logger.debug("Skip restoring active_trade %s: %s", i, e)
            out["active_trades"] = restored
    except Exception as e:
        logger.debug("Could not load trade_data.json: %s", e)
    return out


def save_trade_state():
    """Persist trade_history, active_trades, daily_pnl, trades_today to trade_data.json. Call after any trade change."""
    try:
        if not TRADE_DATA_JSON:
            return
        TRADE_DATA_JSON.parent.mkdir(parents=True, exist_ok=True)
        import json
        from strategy.trade_manager import active_trade_to_dict
        active = _bot_state.get("active_trades") or []
        serialized_active = []
        for item in active:
            if isinstance(item, dict) and "trade" in item:
                t = item["trade"]
                serialized_active.append({
                    "id": item.get("id"),
                    "direction": item.get("direction"),
                    "entry": item.get("entry"),
                    "stop": item.get("stop"),
                    "trade": active_trade_to_dict(t),
                })
        payload = {
            "trade_history": _bot_state.get("trade_history") or [],
            "active_trades": serialized_active,
            "daily_pnl": _bot_state.get("daily_pnl", 0.0),
            "trades_today": _bot_state.get("trades_today", 0),
            "last_trade_date": _bot_state.get("last_trade_date", ""),
        }
        with open(TRADE_DATA_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        logger.warning("Could not save trade_data.json: %s", e)


_bot_state = {
    "scan_active": True,
    "trail_alerts": True,
    "trail_mode": "alert",
    "risk_per_trade": MAX_RISK_PER_TRADE_USD,
    "contracts": DEFAULT_CONTRACTS,
    "use_orderflow": False,
    "session_premarket": True,
    "session_rth": True,
    "trades_today": 0,
    "daily_pnl": 0.0,
    "active_trades": [],
    "trade_history": [],
    "total_scans": 0,
    "last_trade_date": "",
}
# Load persisted risk/contracts
for k, v in _load_persisted_state().items():
    _bot_state[k] = v
# Load persisted trade data (history + active trades + daily_pnl + trades_today)
for k, v in _load_trade_data().items():
    _bot_state[k] = v


def maybe_reset_daily():
    """Reset trades_today and daily_pnl if a new trading day (EST) has started."""
    from bot.scheduler import now_est
    today_str = now_est().strftime("%Y-%m-%d")
    last = _bot_state.get("last_trade_date", "")
    if last != today_str:
        logger.info("New trading day %s (prev=%s) — resetting trades_today=%d, daily_pnl=$%.0f",
                     today_str, last or "none", _bot_state.get("trades_today", 0), _bot_state.get("daily_pnl", 0))
        _bot_state["trades_today"] = 0
        _bot_state["daily_pnl"] = 0.0
        _bot_state["last_trade_date"] = today_str
        _bot_state["total_scans"] = 0
        save_trade_state()

BOT_VERSION = "2.1.0"


def get_state():
    return _bot_state


def get_main_keyboard():
    """Reply keyboard for quick actions."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("▶ Start"), KeyboardButton("⏸ Pause")],
            [KeyboardButton("📊 Status"), KeyboardButton("🔍 Scan status")],
            [KeyboardButton("📂 Positions"), KeyboardButton("💰 Live Price"), KeyboardButton("📈 P&L")],
            [KeyboardButton("📌 Levels"), KeyboardButton("📋 History"), KeyboardButton("🔌 APIs")],
            [KeyboardButton("📉 Chart"), KeyboardButton("📈 Equity"), KeyboardButton("📊 Order flow")],
            [KeyboardButton("🌡 VIX"), KeyboardButton("🤖 ML"), KeyboardButton("❓ Help")],
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
    user = update.effective_user
    logger.info("/start from user %s (%s)", user.id if user else "?", user.first_name if user else "?")
    _bot_state["scan_active"] = True
    await _reply_html(
        update,
        "<b>✅ MNQ Riley Coleman Bot</b>\n"
        "────────────────────\n"
        "Scanning <b>ON</b> • Signals only 7:00–11:00 AM EST\n\n"
        "Use buttons below or <code>/help</code> for commands.",
        reply_markup=get_main_keyboard(),
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("/stop from user %s", update.effective_user.id if update.effective_user else "?")
    _bot_state["scan_active"] = False
    await _reply_html(
        update,
        "⏸ <b>Scanning paused</b>\n\n"
        "Send <code>/start</code> to resume."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("/status from user %s", update.effective_user.id if update.effective_user else "?")
    active = _bot_state["active_trades"]
    scan = "Scanning" if _bot_state["scan_active"] else "Paused"
    total_scans = _bot_state.get("total_scans", 0)

    loop = asyncio.get_event_loop()
    price_line, feed_type = await loop.run_in_executor(None, _fetch_live_price_sync)

    lines = [
        f"<b>📊 {INSTRUMENT} Bot Status</b>",
        "────────────────────",
        f"Mode  <b>LIVE</b>",
        f"Feed  <b>{_esc(feed_type)}</b>",
    ]
    if price_line:
        lines.append(f"Price <code>{price_line}</code>")
    lines += [
        "",
        f"Scan <b>{scan}</b>  │  Scans <code>{total_scans}</code>",
        f"Trades today <code>{_bot_state['trades_today']}</code> / {MAX_TRADES_PER_DAY}",
        f"Daily P&L <code>${_bot_state['daily_pnl']:+,.0f}</code>",
        f"Active trades <b>{len(active)}</b>",
    ]
    for t in active:
        d = t.get("direction", "?")
        e = t.get("entry", 0)
        s = t.get("stop", 0)
        lines.append(f"  • {d} @ <code>{e:,.2f}</code>  Stop <code>{s:,.2f}</code>")
    lines.append(f"\n<i>Session 7:00–11:00 AM EST</i>")
    await _reply_html(update, "\n".join(lines))


async def cmd_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show live running P&L for all open positions."""
    logger.info("/positions from user %s", update.effective_user.id if update.effective_user else "?")
    active = _bot_state["active_trades"]
    if not active:
        await _reply_html(
            update,
            "<b>📂 Open Positions</b>\n"
            "────────────────────\n"
            "No open positions right now.\n\n"
            "<b>Auto:</b> Positions appear here automatically\n"
            "when the bot detects a trade setup.\n\n"
            "<b>Manual:</b> Track your own trade:\n"
            "<code>/addpos LONG 25000 24900 25200</code>\n"
            "<code>/addpos SHORT 25100 25200 24900</code>\n"
            "Format: direction entry stop target [contracts]\n\n"
            "<i>Close with</i> <code>/closepos</code>"
        )
        return

    loop = asyncio.get_event_loop()
    price_str, feed_type = await loop.run_in_executor(None, _fetch_live_price_sync)

    current_price = None
    if price_str:
        try:
            current_price = float(price_str.replace(",", ""))
        except ValueError:
            pass

    from config import TICK_VALUE_USD
    total_pnl = 0.0
    lines = [
        f"<b>📂 Open Positions ({len(active)})</b>",
        "────────────────────",
    ]
    if price_str:
        lines.append(f"NQ Price <code>{price_str}</code>  <i>({_esc(feed_type)})</i>")
        lines.append("")

    for idx, item in enumerate(active):
        trade = item.get("trade")
        if trade is None:
            continue
        pos_id = item.get("id", idx + 1)
        direction = trade.direction
        entry = trade.entry
        stop = trade.current_stop
        contracts = trade.contracts
        arrow = "🟢" if direction == "LONG" else "🔴"

        if current_price is not None:
            pnl = trade.pnl_at_price(current_price)
            rr = trade.rr_at_price(current_price)
            total_pnl += pnl
            pnl_sign = "+" if pnl >= 0 else ""
            rr_sign = "+" if rr >= 0 else ""
            pnl_emoji = "🟩" if pnl >= 0 else "🟥"
            lines.append(
                f"{arrow} <b>#{pos_id} {direction}</b>  ×{contracts}\n"
                f"  Entry <code>{entry:,.2f}</code>  Stop <code>{stop:,.2f}</code>\n"
                f"  TP1 <code>{trade.target1:,.2f}</code>  TP2 <code>{trade.target2:,.2f}</code>\n"
                f"  {pnl_emoji} P&L <b><code>{pnl_sign}${pnl:,.2f}</code></b>  "
                f"R <code>{rr_sign}{rr:.2f}R</code>"
            )
        else:
            lines.append(
                f"{arrow} <b>#{pos_id} {direction}</b>  ×{contracts}\n"
                f"  Entry <code>{entry:,.2f}</code>  Stop <code>{stop:,.2f}</code>\n"
                f"  TP1 <code>{trade.target1:,.2f}</code>  TP2 <code>{trade.target2:,.2f}</code>\n"
                f"  <i>Price unavailable</i>"
            )

    if current_price is not None and len(active) > 1:
        lines.append("")
        pnl_sign = "+" if total_pnl >= 0 else ""
        lines.append(f"<b>Total P&L  <code>{pnl_sign}${total_pnl:,.2f}</code></b>")

    if current_price is not None:
        lines.append("")
        total_sign = "+" if total_pnl >= 0 else ""
        combined = _bot_state.get("daily_pnl", 0.0) + total_pnl
        combined_sign = "+" if combined >= 0 else ""
        lines.append(
            f"Closed P&L <code>${_bot_state.get('daily_pnl', 0.0):+,.0f}</code>  │  "
            f"Open <code>{total_sign}${total_pnl:,.0f}</code>  │  "
            f"Day <code>{combined_sign}${combined:,.0f}</code>"
        )

    lines.append(f"\n<code>/closepos</code> to close  │  <code>/addpos</code> to add")
    lines.append(f"<i>Updated {now_est().strftime('%I:%M:%S %p EST')}</i>")
    await _reply_html(update, "\n".join(lines))


async def cmd_addpos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually add a position to track.
    Usage: /addpos LONG 25000 24900 25200 [contracts]
           /addpos SHORT 25100 25200 24900 [contracts]
    """
    logger.info("/addpos from user %s: %s", update.effective_user.id if update.effective_user else "?", context.args)
    usage = (
        "<b>Usage:</b>\n"
        "<code>/addpos LONG entry stop target [contracts]</code>\n"
        "<code>/addpos SHORT entry stop target [contracts]</code>\n\n"
        "<b>Example:</b>\n"
        "<code>/addpos LONG 25000 24900 25200 2</code>\n"
        "<code>/addpos SHORT 25100 25200 24900 1</code>"
    )
    args = context.args or []
    if len(args) < 4:
        await _reply_html(update, f"<b>📂 Add Position</b>\n────────────────────\n{usage}")
        return

    direction = args[0].upper()
    if direction not in ("LONG", "SHORT"):
        await _reply_html(update, f"❌ Direction must be <b>LONG</b> or <b>SHORT</b>.\n\n{usage}")
        return

    try:
        entry = float(args[1])
        stop = float(args[2])
        target = float(args[3])
        contracts = int(args[4]) if len(args) > 4 else 1
    except ValueError:
        await _reply_html(update, f"❌ Invalid numbers.\n\n{usage}")
        return

    if contracts < 1:
        contracts = 1

    if direction == "LONG" and stop >= entry:
        await _reply_html(update, "❌ For LONG, stop must be <b>below</b> entry.")
        return
    if direction == "SHORT" and stop <= entry:
        await _reply_html(update, "❌ For SHORT, stop must be <b>above</b> entry.")
        return

    from strategy.trade_manager import ActiveTrade
    from config import TICK_VALUE_USD
    risk_pts = abs(entry - stop)
    trade = ActiveTrade(
        direction=direction,
        entry=entry,
        stop=stop,
        target1=target,
        target2=target + (target - entry) if direction == "LONG" else target - (entry - target),
        contracts=contracts,
        risk_per_contract_usd=risk_pts * TICK_VALUE_USD,
    )

    state = get_state()
    pos_id = len(state["active_trades"]) + 1
    state["active_trades"].append({
        "trade": trade,
        "id": pos_id,
        "direction": trade.direction,
        "entry": trade.entry,
        "stop": trade.current_stop,
    })
    save_trade_state()

    arrow = "🟢" if direction == "LONG" else "🔴"
    await _reply_html(
        update,
        f"<b>✅ Position #{pos_id} Added</b>\n"
        f"────────────────────\n"
        f"{arrow} <b>{direction}</b> ×{contracts}\n"
        f"Entry <code>{entry:,.2f}</code>\n"
        f"Stop  <code>{stop:,.2f}</code>\n"
        f"TP1   <code>{target:,.2f}</code>\n"
        f"Risk  <code>{risk_pts:.2f} pts</code> (${risk_pts * TICK_VALUE_USD * contracts:,.0f})\n\n"
        f"Tap <b>📂 Positions</b> to see live P&L."
    )


async def cmd_closepos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Close/remove a tracked position.
    Usage: /closepos [id]  — close specific position, or /closepos all
    """
    logger.info("/closepos from user %s: %s", update.effective_user.id if update.effective_user else "?", context.args)
    state = get_state()
    active = state["active_trades"]

    if not active:
        await _reply_html(update, "📂 No open positions to close.")
        return

    args = context.args or []

    if args and args[0].lower() == "all":
        count = len(active)
        loop = asyncio.get_event_loop()
        price_str, _ = await loop.run_in_executor(None, _fetch_live_price_sync)
        total_pnl = 0.0
        if price_str:
            try:
                current_price = float(price_str.replace(",", ""))
                for item in active:
                    trade = item.get("trade")
                    if trade:
                        total_pnl += trade.pnl_at_price(current_price)
            except ValueError:
                pass
        state["daily_pnl"] += total_pnl
        for item in active:
            trade = item.get("trade")
            if trade:
                state["trade_history"].append({
                    "dir": trade.direction, "entry": trade.entry,
                    "result": "closed", "pnl": trade.pnl_at_price(current_price) if price_str else 0,
                    "date": now_est().strftime("%Y-%m-%d"),
                })
        state["active_trades"] = []
        save_trade_state()
        await _reply_html(
            update,
            f"✅ Closed <b>{count}</b> position(s).\n"
            f"Realized P&L: <code>${total_pnl:+,.2f}</code>"
        )
        return

    if args:
        try:
            target_id = int(args[0])
        except ValueError:
            await _reply_html(update, "❌ Usage: <code>/closepos [id]</code> or <code>/closepos all</code>")
            return
    else:
        target_id = active[-1].get("id", 1) if active else None

    removed = None
    remaining = []
    for item in active:
        if item.get("id") == target_id and removed is None:
            removed = item
        else:
            remaining.append(item)

    if removed is None:
        ids = ", ".join(str(i.get("id", "?")) for i in active)
        await _reply_html(update, f"❌ Position #{target_id} not found.\nOpen IDs: {ids}")
        return

    trade = removed.get("trade")
    pnl = 0.0
    if trade:
        loop = asyncio.get_event_loop()
        price_str, _ = await loop.run_in_executor(None, _fetch_live_price_sync)
        if price_str:
            try:
                current_price = float(price_str.replace(",", ""))
                pnl = trade.pnl_at_price(current_price)
            except ValueError:
                pass
        state["daily_pnl"] += pnl
        state["trade_history"].append({
            "dir": trade.direction, "entry": trade.entry,
            "result": "closed", "pnl": pnl,
            "date": now_est().strftime("%Y-%m-%d"),
        })

    state["active_trades"] = remaining
    save_trade_state()
    arrow = "🟢" if removed.get("direction") == "LONG" else "🔴"
    await _reply_html(
        update,
        f"✅ <b>Position #{target_id} Closed</b>\n"
        f"────────────────────\n"
        f"{arrow} {removed.get('direction', '?')} @ <code>{removed.get('entry', 0):,.2f}</code>\n"
        f"Realized P&L: <code>${pnl:+,.2f}</code>\n"
        f"Remaining: <b>{len(remaining)}</b> position(s)"
    )


async def cmd_scan_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show whether scanning is on/off and total number of scans run."""
    on = _bot_state.get("scan_active", True)
    total = _bot_state.get("total_scans", 0)
    status = "ON" if on else "OFF"
    msg = (
        "<b>🔍 Scan Status</b>\n"
        "────────────────────\n"
        f"Scanning: <b>{status}</b>\n"
        f"Total scans run: <b><code>{total}</code></b>\n\n"
        "Scans run only during 7:00–11:00 AM EST when scanning is ON."
    )
    await _reply_html(update, msg)


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
        # Get price first; for Yahoo, connection is established inside get_current_price()
        price = feed.get_current_price()
        if price is not None:
            return f"{price:,.2f}", feed_type
        # No price: show feed type and connection state so user can debug
        conn = "connected" if feed.is_connected() else "not connected"
        return "", f"{feed_type} ({conn})"
    except Exception as e:
        return "", f"{type(e).__name__}: {e}"


def _live_price_inline_keyboard():
    """Inline buttons to toggle Yahoo WebSocket (live price source)."""
    on = get_use_yahoo_ws_realtime()
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🟢 WebSocket On" if on else "WebSocket On", callback_data="yahoo_ws_on"),
            InlineKeyboardButton("⚪ REST only" if not on else "REST only", callback_data="yahoo_ws_off"),
        ],
    ])


async def cmd_live_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show live MNQ price (button or /price) with toggle for WebSocket on/off."""
    loop = asyncio.get_event_loop()
    price_line, feed_info = await loop.run_in_executor(None, _fetch_live_price_sync)
    if price_line:
        msg = (
            f"<b>💰 {INSTRUMENT} Live Price</b>\n"
            "────────────────────\n"
            f"<b><code>{price_line}</code></b>\n\n"
            f"<i>Source: {_esc(feed_info)}</i>\n"
            "Tap a button below to change price source:"
        )
    else:
        msg = (
            f"<b>💰 {INSTRUMENT} Live Price</b>\n"
            "────────────────────\n"
            "No price available.\n\n"
            f"<i>Feed: {_esc(feed_info)}</i>\n\n"
            "Tap <b>⚪ REST only</b> if you're on a restricted server, then tap 💰 Live Price again."
        )
    await update.message.reply_text(
        msg,
        parse_mode="HTML",
        reply_markup=_live_price_inline_keyboard(),
    )


async def callback_feed_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button: Yahoo WebSocket On / REST only."""
    query = update.callback_query
    if not query or not query.data:
        return
    # Answer immediately so Telegram stops loading and user sees feedback
    try:
        await query.answer(text="Updating…")
    except Exception:
        await query.answer()
    if query.data not in ("yahoo_ws_on", "yahoo_ws_off"):
        return
    enabled = query.data == "yahoo_ws_on"
    try:
        set_use_yahoo_ws_realtime(enabled)
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {_esc(str(e))}", parse_mode="HTML")
        return
    status = "WebSocket (minimal delay)" if enabled else "REST only (no extra threads)"
    # Include timestamp so Telegram accepts the edit (avoids "message not modified")
    updated = now_est().strftime("%I:%M %p EST")
    new_text = (
        f"<b>💰 {INSTRUMENT} Live Price</b>\n"
        "────────────────────\n"
        f"✅ <b>Price source set to: {_esc(status)}</b>\n\n"
        f"<i>Updated {_esc(updated)}</i>\n\n"
        "Tap <b>💰 Live Price</b> again to see current price and change source."
    )
    try:
        await query.edit_message_text(
            new_text,
            parse_mode="HTML",
            reply_markup=_live_price_inline_keyboard(),
        )
    except Exception as e:
        logger.warning("Could not edit Live Price message: %s", e)
        try:
            await query.message.reply_text(
                f"✅ Price source set to <b>{_esc(status)}</b>. Tap 💰 Live Price to refresh.",
                parse_mode="HTML",
            )
        except Exception:
            pass


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
    logger.info("/help from user %s", update.effective_user.id if update.effective_user else "?")
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
        "<code>/positions</code> – Live open P&L per position\n"
        "<code>/addpos</code> – Manually track a position\n"
        "<code>/closepos</code> – Close a tracked position\n"
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
        "<code>/backtest [days]</code> – Run short backtest (default 2 days)\n\n"
        "<b>Advanced</b>\n"
        "<code>/chart</code> – Live chart with key levels\n"
        "<code>/equity</code> – Equity curve chart + stats\n"
        "<code>/vix</code> – VIX filter status\n"
        "<code>/ml</code> – AI/ML signal filter weights\n"
        "<code>/instruments</code> – Multi-instrument config\n"
        "<code>/dashboard</code> – Web dashboard info"
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


async def cmd_chart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a chart image with price action and key levels."""
    await _reply_html(update, "<b>Generating chart...</b>")
    loop = asyncio.get_event_loop()
    chart_bytes, error = await loop.run_in_executor(None, _generate_chart_sync)
    if error:
        await _reply_html(update, f"<b>Chart error:</b> {_esc(error)}")
        return
    ok = await send_photo_all(chart_bytes, context.bot, caption="<b>MNQ - Live Chart with Key Levels</b>")
    if not ok:
        await _reply_html(update, "Failed to send chart.")


def _generate_chart_sync() -> tuple[bytes | None, str | None]:
    try:
        from data import get_feed
        from main import get_levels_on_demand
        from utils.chart_generator import generate_price_chart
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        df_1m = feed.get_1m_candles(100)
        if df_1m is None or df_1m.empty:
            return None, "No candle data. Try during 7:00-11:00 AM EST."
        key_levels = None
        try:
            from strategy import build_key_levels
            from .scheduler import now_est
            df_15m = feed.get_15m_candles(50)
            if df_15m is not None and not df_15m.empty:
                key_levels = build_key_levels(df_15m, df_1m, now_est())
        except Exception:
            pass
        active = _bot_state.get("active_trades", [])
        png = generate_price_chart(df_1m, key_levels=key_levels, active_trades=active)
        return png, None
    except Exception as e:
        return None, str(e)


async def cmd_equity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send equity curve chart and stats."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _equity_sync)
    if result.get("error"):
        await _reply_html(update, f"<b>Equity:</b> {_esc(result['error'])}")
        return
    stats = result.get("stats", {})
    msg = (
        "<b>📈 Equity Curve</b>\n"
        "────────────────────\n"
        f"Current  <code>${stats.get('current_balance', 0):,.0f}</code>\n"
        f"Peak     <code>${stats.get('peak_balance', 0):,.0f}</code>\n"
        f"Return   <code>{stats.get('total_return_pct', 0):+.2f}%</code>\n"
        f"Max DD   <code>${stats.get('max_drawdown_usd', 0):,.0f}</code> ({stats.get('max_drawdown_pct', 0):.2f}%)\n"
        f"Sharpe   <code>{stats.get('sharpe_estimate', 0):.2f}</code>"
    )
    chart_bytes = result.get("chart")
    if chart_bytes:
        await send_photo_all(chart_bytes, context.bot, caption=msg)
    else:
        await _reply_html(update, msg)


def _equity_sync() -> dict:
    try:
        from data.equity_tracker import get_equity_stats, generate_equity_chart
        stats = get_equity_stats()
        chart = generate_equity_chart()
        return {"stats": stats, "chart": chart}
    except Exception as e:
        return {"error": str(e)}


async def cmd_vix(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current VIX and filter status."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _vix_sync)
    vix = result.get("vix")
    action = result.get("action", "normal")
    if vix is None:
        await _reply_html(update, "<b>VIX Filter</b>\n────────────────────\nCould not fetch VIX (market may be closed).")
        return
    emoji = {"block": "🔴", "reduce": "🟡", "normal": "🟢"}.get(action, "⚪")
    msg = (
        "<b>VIX Filter</b>\n"
        "────────────────────\n"
        f"VIX <b><code>{vix:.1f}</code></b> {emoji}\n"
        f"Action: <b>{action.upper()}</b>\n"
    )
    if action == "block":
        msg += "\n<i>Trading blocked: VIX too high (>30)</i>"
    elif action == "reduce":
        msg += "\n<i>Risk reduced by 50%: VIX elevated (>25)</i>"
    else:
        msg += "\n<i>Normal conditions</i>"
    await _reply_html(update, msg)


def _vix_sync() -> dict:
    try:
        from data.vix_filter import vix_check
        return vix_check()
    except Exception as e:
        return {"action": "normal", "vix": None, "reason": str(e)}


async def cmd_ml(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show ML filter status and weights."""
    try:
        from strategy.ml_filter import _load_weights, DEFAULT_WEIGHTS
        weights = _load_weights()
        lines = ["<b>AI/ML Signal Filter</b>", "────────────────────", ""]
        for k, v in weights.items():
            default = DEFAULT_WEIGHTS.get(k, 0)
            diff = v - default
            arrow = "+" if diff > 0 else ""
            lines.append(f"<code>{k:<25}</code> <b>{v:.3f}</b>  ({arrow}{diff:.3f})")
        lines.append("")
        lines.append("<i>Weights auto-adjust from trade outcomes.</i>")
        await _reply_html(update, "\n".join(lines))
    except Exception as e:
        await _reply_html(update, f"<b>ML Filter:</b> {_esc(str(e))}")


async def cmd_instruments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show configured instruments."""
    from config import INSTRUMENTS, ACTIVE_INSTRUMENTS
    lines = ["<b>Multi-Instrument Config</b>", "────────────────────", ""]
    for sym, info in INSTRUMENTS.items():
        active = "✅" if sym in ACTIVE_INSTRUMENTS else "  "
        lines.append(f"{active} <b>{sym}</b> - {info['name']} (${info['tick_value']}/pt, {info['symbol']})")
    lines.append(f"\n<i>Active: {', '.join(ACTIVE_INSTRUMENTS)}</i>")
    lines.append("<i>Set MNQ_ACTIVE_INSTRUMENTS=MNQ,ES to add more.</i>")
    await _reply_html(update, "\n".join(lines))


async def cmd_dashboard_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show web dashboard URL."""
    from config import DASHBOARD_PORT
    await _reply_html(
        update,
        "<b>Web Dashboard</b>\n"
        "────────────────────\n"
        f"Run: <code>python -m dashboard.app</code>\n"
        f"URL: <code>http://localhost:{DASHBOARD_PORT}</code>\n\n"
        "<i>Dark theme with live charts, P&L, trades.</i>"
    )


async def handle_keyboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route button text to the right command."""
    text = (update.message and update.message.text or "").strip()
    user = update.effective_user
    user_id = user.id if user else "?"
    logger.info("Button press from %s: '%s'", user_id, text)

    handler_map = {
        "▶ Start": cmd_start,
        "⏸ Pause": cmd_stop,
        "📊 Status": cmd_status,
        "🔍 Scan status": cmd_scan_status,
        "📂 Positions": cmd_positions,
        "📌 Levels": cmd_levels,
        "📈 P&L": cmd_pnl,
        "📋 History": cmd_history,
        "📊 Order flow": cmd_orderflow_toggle,
        "💰 Live Price": cmd_live_price,
        "🔌 APIs": cmd_apis,
        "📉 Chart": cmd_chart,
        "📈 Equity": cmd_equity,
        "🌡 VIX": cmd_vix,
        "🤖 ML": cmd_ml,
        "🌐 Dashboard": cmd_dashboard_info,
        "❓ Help": cmd_help,
    }

    handler = handler_map.get(text)
    if handler:
        try:
            await handler(update, context)
        except Exception as e:
            logger.error("Button handler error for '%s': %s", text, e, exc_info=True)
            try:
                await _reply_html(update, f"Error: {_esc(str(e)[:200])}")
            except Exception:
                pass
    else:
        logger.debug("Unrecognized button text: '%s'", text)


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
    if not TELEGRAM_CHAT_IDS:
        await _reply_html(update, "❌ No <code>TELEGRAM_CHAT_ID</code> (or TELEGRAM_CHAT_IDS) set.")
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
    ok = await send_telegram_all(msg, context.bot)
    if ok:
        await _reply_html(update, "✅ Demo signal sent to your chat.")
    else:
        await _reply_html(update, "❌ Failed to send demo signal.")


async def cmd_demo_trail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a demo trail-stop alert (no real trade)."""
    if not TELEGRAM_CHAT_IDS:
        await _reply_html(update, "❌ No <code>TELEGRAM_CHAT_ID</code> (or TELEGRAM_CHAT_IDS) set.")
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
    ok = await send_telegram_all(msg, context.bot)
    if ok:
        await _reply_html(update, "✅ Demo trail alert sent to your chat.")
    else:
        await _reply_html(update, "❌ Failed to send demo trail alert.")


async def cmd_demo_levels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a demo key levels message (sample values)."""
    if not TELEGRAM_CHAT_IDS:
        await _reply_html(update, "❌ No <code>TELEGRAM_CHAT_ID</code> (or TELEGRAM_CHAT_IDS) set.")
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
    ok = await send_telegram_all(msg, context.bot)
    if ok:
        await _reply_html(update, "✅ Demo levels sent to your chat.")
    else:
        await _reply_html(update, "❌ Failed to send demo levels.")


def register_commands(application):
    """Register all command handlers and keyboard button handler."""
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("positions", cmd_positions))
    application.add_handler(CommandHandler("addpos", cmd_addpos))
    application.add_handler(CommandHandler("closepos", cmd_closepos))
    application.add_handler(CommandHandler("scanstatus", cmd_scan_status))
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
    application.add_handler(CommandHandler("chart", cmd_chart))
    application.add_handler(CommandHandler("equity", cmd_equity))
    application.add_handler(CommandHandler("vix", cmd_vix))
    application.add_handler(CommandHandler("ml", cmd_ml))
    application.add_handler(CommandHandler("instruments", cmd_instruments))
    application.add_handler(CommandHandler("dashboard", cmd_dashboard_info))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("pause", cmd_stop))
    application.add_handler(CallbackQueryHandler(callback_feed_toggle, pattern="^yahoo_ws_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_keyboard_button))