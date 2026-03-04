"""
Alert message formatting and sending for Telegram.
Uses HTML for a refined, scannable UI.
"""

from __future__ import annotations

import html
import logging
from typing import Optional

from config import INSTRUMENT, TICK_VALUE_USD, TELEGRAM_CHAT_IDS

logger = logging.getLogger(__name__)


def _esc(s: str) -> str:
    """Escape for Telegram HTML."""
    return html.escape(str(s), quote=False)


def _n(x: float) -> str:
    """Format number with commas."""
    return f"{x:,.2f}"


def format_trade_alert(
    setup_name: str,
    time_est: str,
    direction: str,
    entry: float,
    stop: float,
    tp1: float,
    tp2: float,
    rr_ratio: float,
    confidence: str,
    timeframe_note: str,
    key_level: str,
    notes: str,
) -> str:
    """Format the main trade alert with clear sections."""
    pts_sl = abs(entry - stop)
    pts_tp1 = abs(tp1 - entry)
    pts_tp2 = abs(tp2 - entry)
    usd_sl = pts_sl * TICK_VALUE_USD
    usd_tp1 = pts_tp1 * TICK_VALUE_USD
    usd_tp2 = pts_tp2 * TICK_VALUE_USD
    dir_emoji = "🟢" if direction == "LONG" else "🔴"
    return (
        f"<b>🔔 MNQ TRADE ALERT</b>\n"
        f"<i>Riley Coleman • {_esc(setup_name)}</i>\n"
        "────────────────────\n"
        f"<b>{dir_emoji} {direction}</b>  │  ⏰ {_esc(time_est)}\n\n"
        "<b>📍 Levels</b>\n"
        f"Entry   <code>{_n(entry)}</code>\n"
        f"Stop    <code>{_n(stop)}</code>  (-{pts_sl:.0f} pts │ -${usd_sl:.0f}/ct)\n"
        f"TP1 50% <code>{_n(tp1)}</code>  (+{pts_tp1:.0f} pts │ +${usd_tp1:.0f}/ct)\n"
        f"TP2 50% <code>{_n(tp2)}</code>  (+{pts_tp2:.0f} pts │ +${usd_tp2:.0f}/ct)\n\n"
        f"<b>📐 R:R</b> <code>{rr_ratio:.1f}:1</code>  │  <b>Confidence</b> {_esc(confidence)}\n"
        f"<b>📊</b> {_esc(timeframe_note)}\n"
        f"<b>🗝 Level</b> {_esc(key_level)}\n"
        f"<i>{_esc(notes)}</i>"
    )


def format_trail_alert(
    direction: str,
    entry: float,
    current_price: float,
    floating_r: float,
    action: str,
    new_stop: float,
    locked_comment: str,
    target2: Optional[float] = None,
    tip: str = "",
) -> str:
    """Trail your stop – refined layout."""
    pnl = (current_price - entry) if direction == "LONG" else (entry - current_price)
    pnl_usd = pnl * TICK_VALUE_USD
    dir_emoji = "🟢" if direction == "LONG" else "🔴"
    body = (
        f"<b>🔄 TRAIL STOP – MNQ</b>\n"
        "────────────────────\n"
        f"<b>{dir_emoji} {direction}</b> from <code>{_n(entry)}</code>\n"
        f"Price now <code>{_n(current_price)}</code>\n"
        f"Floating <b>${pnl_usd:.0f}/ct</b> (+{floating_r:.1f}R)\n\n"
        f"<b>✅ {_esc(action)}</b>\n"
        f"New stop <code>{_n(new_stop)}</code> {_esc(locked_comment)}\n"
    )
    if target2 is not None:
        body += f"\n🎯 Target 2: <code>{_n(target2)}</code>\n"
    if tip:
        body += f"\n💡 {_esc(tip)}\n"
    return body


def format_caution_pullback(
    direction: str,
    entry: float,
    price_from: float,
    price_to: float,
    trailed_stop: float,
) -> str:
    return (
        "<b>⚠️ CAUTION – Pullback</b>\n"
        "────────────────────\n"
        f"<b>{direction}</b> from <code>{_n(entry)}</code>\n"
        f"Price {_n(price_from)} → <code>{_n(price_to)}</code>\n"
        f"Trailed stop at <code>{_n(trailed_stop)}</code>\n\n"
        "<i>Watch closely. Do not move stop lower.</i>"
    )


def format_stop_hit(
    direction: str,
    entry: float,
    stop_price: float,
    result_usd: float,
    result_r: str,
    daily_pnl: Optional[float] = None,
) -> str:
    msg = (
        "<b>🔒 TRADE CLOSED</b>\n"
        "────────────────────\n"
        f"<b>{direction}</b> from <code>{_n(entry)}</code>\n"
        f"Stopped at <code>{_n(stop_price)}</code>\n"
        f"Result <b>${result_usd:.0f}/ct</b> ({_esc(result_r)})\n\n"
        "✅ Discipline – you protected capital."
    )
    if daily_pnl is not None:
        msg += f"\n\n<b>📊 Daily P&L</b> <code>${daily_pnl:+,.0f}</code>"
    return msg


def format_daily_summary(
    date_str: str,
    trades_taken: int,
    winners: int,
    losers: int,
    pnl: float,
    win_rate_pct: float,
    trade_lines: list[str],
) -> str:
    pnl_emoji = "📈" if pnl >= 0 else "📉"
    body = (
        f"<b>📅 DAILY SUMMARY</b> – {_esc(date_str)}\n"
        "────────────────────\n"
        f"Trades <b>{trades_taken}</b>  │  ✅ {winners}  │  ❌ {losers}\n"
        f"Win rate <b>{win_rate_pct:.0f}%</b>\n"
        f"{pnl_emoji} P&L <code>${pnl:+,.0f}</code>\n\n"
    )
    if trade_lines:
        body += "<b>Today's trades</b>\n"
        for line in trade_lines:
            body += f"• {_esc(line)}\n"
    body += "\n<i>Next session: 7:00 AM EST</i>"
    return body


async def send_telegram(text: str, bot, chat_id: str, parse_mode: str = "HTML") -> bool:
    """Send message to Telegram. Uses HTML by default for refined UI."""
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        return True
    except Exception as e:
        logger.exception("Telegram send failed: %s", e)
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            pass
        return False


async def send_telegram_all(text: str, bot, parse_mode: str = "HTML") -> bool:
    """Send message to all configured chat IDs (all users with bot access). Returns True if at least one send succeeded."""
    if not TELEGRAM_CHAT_IDS:
        return False
    ok = False
    for chat_id in TELEGRAM_CHAT_IDS:
        if await send_telegram(text, bot, chat_id, parse_mode):
            ok = True
    return ok
