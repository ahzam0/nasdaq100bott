"""
MNQ Trading Bot – Riley Coleman Strategy
Entry point: Telegram bot + scan loop + trailing alerts + daily summary.

Crash-hardened: every scheduled job is wrapped in try/except so a single
failure never kills the repeating timer.  The main() loop auto-restarts
polling on network errors with exponential back-off.
"""

from __future__ import annotations

import asyncio
import gc
import html
import logging
import os
import signal
import sys
import threading
import traceback
import warnings
from datetime import date, time, datetime, timedelta
from functools import wraps
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure project root on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    ACTIVE_STRATEGY,
    AUTO_EXECUTE,
    BROKER,
    INSTRUMENT,
    USE_LIVE_FEED,
    PRICE_API_URL,
    LEVEL_TOLERANCE_PTS,
    MAX_DAILY_LOSS_USD,
    MAX_RISK_PTS,
    MAX_TRADES_PER_DAY,
    MIN_RR_RATIO,
    REQUIRE_TREND_ONLY,
    RETEST_ONLY,
    MIN_BODY_PTS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_CHAT_IDS,
    SHOW_SCAN_STATUS,
    SCAN_STATUS_INTERVAL_MINUTES,
    TRAIL_ALERTS_ENABLED,
    TRAIL_MODE,
    TARGET_MIN_TRADES_PER_DAY,
    FALLBACK_AFTER_MINUTES,
    FALLBACK_MIN_RR,
    TP1_RR,
    TP2_RR,
    AUTO_RETRAIN_ENABLED,
    RETRAIN_DAY_OF_WEEK,
    RETRAIN_HOUR_EST,
    RETRAIN_MINUTE_EST,
    RTH_END,
    SCAN_SESSION_EST,
    SKIP_MONDAY,
    SKIP_CPI_DAYS,
    SKIP_FOMC_DAYS,
    SKIP_NFP_DAYS,
    VIX_FILTER_ENABLED,
    VIX_BLOCK_THRESHOLD,
    VIX_REDUCE_THRESHOLD,
    DYNAMIC_SIZING_ENABLED,
    ML_FILTER_ENABLED,
    ML_FILTER_THRESHOLD,
    WEEKLY_REPORT_DAY,
    WEEKLY_REPORT_HOUR,
    REALTIME_ORDERFLOW_ENABLED,
    ALPACA_DATA_API_KEY,
    ALPACA_DATA_SECRET_KEY,
    FINNHUB_API_KEY,
)
from data import get_feed
from strategy import (
    build_key_levels,
    detect_setup,
    swing_highs_lows,
    trend_from_structure,
    validate_entry,
    ActiveTrade,
    next_milestone_to_trail,
    stop_for_milestone,
)
from bot import (
    register_commands,
    get_state,
    save_trade_state,
    maybe_reset_daily,
    format_trade_alert,
    format_trail_alert,
    format_stop_hit,
    format_daily_summary,
    send_telegram,
    send_telegram_all,
    now_est,
    in_scan_window,
    in_trade_window,
)
import pandas as pd
from news_filter import should_trade_today
from data.feed import start_live_feed_session, end_live_feed_session
from broker import get_broker
from utils import setup_logging, log_trade, contracts_from_risk

from telegram.error import Conflict, NetworkError, TimedOut, RetryAfter
from telegram.ext import Application, ContextTypes
from telegram.warnings import PTBUserWarning

logger = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")


def _parse_session_end_time():
    """Parse RTH_END (e.g. '11:00') to datetime.time for run_daily."""
    parts = RTH_END.strip().split(":")
    hour = int(parts[0]) if parts else 11
    minute = int(parts[1]) if len(parts) > 1 else 0
    return time(hour, minute, tzinfo=EST)


# ---------------------------------------------------------------------------
# Crash-guard decorator: wraps every PTB job callback so an unhandled
# exception is logged but never propagates (which would kill the timer).
# ---------------------------------------------------------------------------
def _safe_job(func):
    """Decorator that catches all exceptions in PTB job callbacks."""
    @wraps(func)
    async def wrapper(context: ContextTypes.DEFAULT_TYPE):
        try:
            await func(context)
        except (NetworkError, TimedOut, OSError) as e:
            logger.warning("Network error in %s (will retry next cycle): %s", func.__name__, e)
        except RetryAfter as e:
            logger.warning("Telegram rate limit in %s: retry after %s s", func.__name__, e.retry_after)
            await asyncio.sleep(min(e.retry_after, 60))
        except Exception:
            logger.error("Unhandled error in %s – job continues:\n%s", func.__name__, traceback.format_exc())
    return wrapper


# Heartbeat: track last successful scan so we can detect silent hangs
_last_heartbeat: datetime | None = None
_consecutive_job_errors: int = 0
MAX_CONSECUTIVE_JOB_ERRORS = 20


SCAN_FAILURE_ALERT_THRESHOLD = 5  # Alert after this many consecutive feed/data failures


async def _record_scan_failure(state: dict, bot, reason: str) -> None:
    """Increment consecutive scan failures and send Telegram alert after threshold."""
    state["consecutive_scan_failures"] = state.get("consecutive_scan_failures", 0) + 1
    if state["consecutive_scan_failures"] >= SCAN_FAILURE_ALERT_THRESHOLD and not state.get("scan_failure_alert_sent"):
        state["scan_failure_alert_sent"] = True
        msg = (
            f"<b>⚠️ Scan failures</b>\n"
            f"────────────────────\n"
            f"<code>{state['consecutive_scan_failures']}</code> consecutive failures (data/feed).\n"
            f"Last reason: {html.escape(reason)}\n\n"
            "<i>Check feed, network, and session. Bot will keep retrying.</i>"
        )
        await send_telegram_all(msg, bot)


async def _run_single_strategy(
    bot,
    state: dict,
    now,
    vix_factor: float,
    max_trades: int,
    df_1m,
    df_15m,
    key_levels,
    swing_highs,
    swing_lows,
    trend,
    current_price: float,
) -> None:
    """Run detection + trade processing for Riley (Trend & Key Levels) only."""
    setup = detect_setup(
        df_1m, df_15m, key_levels, swing_highs, swing_lows, trend,
        level_tolerance_pts=LEVEL_TOLERANCE_PTS,
        require_trend_only=REQUIRE_TREND_ONLY,
        retest_only=RETEST_ONLY,
        min_body_pts=MIN_BODY_PTS,
    )
    if setup is None:
        await _send_scan_status(bot, now, key_levels, trend, current_price, state["trades_today"], "No setup")
        return

    setup_name_label = setup.setup_type.value
    risk_pts = abs(setup.entry_price - setup.stop_price)

    if TP1_RR > 0 and risk_pts > 0:
        if setup.direction == "LONG":
            setup.target1_price = setup.entry_price + risk_pts * TP1_RR
        else:
            setup.target1_price = setup.entry_price - risk_pts * TP1_RR
    if TP2_RR > 0 and risk_pts > 0:
        if setup.direction == "LONG":
            setup.target2_price = setup.entry_price + risk_pts * TP2_RR
        else:
            setup.target2_price = setup.entry_price - risk_pts * TP2_RR

    if MAX_RISK_PTS is not None and risk_pts > MAX_RISK_PTS:
        await _send_scan_status(bot, now, key_levels, trend, current_price, state["trades_today"], "No setup (stop too wide)")
        return

    mins_since_7 = (now.hour - 7) * 60 + now.minute if 7 <= now.hour < 12 else 0
    use_fallback_rr = (
        TARGET_MIN_TRADES_PER_DAY >= 1
        and FALLBACK_AFTER_MINUTES > 0
        and FALLBACK_MIN_RR is not None
        and state["trades_today"] == 0
        and mins_since_7 >= FALLBACK_AFTER_MINUTES
    )
    min_rr_use = FALLBACK_MIN_RR if use_fallback_rr else MIN_RR_RATIO
    if TP1_RR > 0:
        min_rr_use = TP1_RR

    result = validate_entry(
        setup, now, state["trades_today"], max_trades,
        min_rr_ratio=min_rr_use,
        orderflow_summary=None,
    )
    if not result.valid:
        logger.info("Entry rejected: %s", result.reason)
        await _send_scan_status(bot, now, key_levels, trend, current_price, state["trades_today"], f"Rejected: {result.reason}")
        return

    ml_score = None
    if ML_FILTER_ENABLED:
        try:
            from strategy.ml_filter import ml_filter_check
            ml_result = ml_filter_check(setup, df_1m, trend, threshold=ML_FILTER_THRESHOLD, now_est=now)
            ml_score = ml_result.get("score")
            if not ml_result.get("pass"):
                logger.info("ML filter rejected setup: score=%.3f (threshold=%.2f)", ml_score, ML_FILTER_THRESHOLD)
                await _send_scan_status(bot, now, key_levels, trend, current_price, state["trades_today"], f"ML filter: score {ml_score:.2f}")
                return
        except Exception as e:
            logger.debug("ML filter skipped: %s", e)

    effective_risk = state["risk_per_trade"]
    if DYNAMIC_SIZING_ENABLED:
        try:
            from utils.risk_calculator import dynamic_risk, get_streak
            win_streak, loss_streak = get_streak(state.get("trade_history", []))
            current_balance = 50000.0 + state.get("daily_pnl", 0)
            effective_risk = dynamic_risk(
                base_risk_usd=state["risk_per_trade"],
                current_balance=current_balance,
                win_streak=win_streak,
                loss_streak=loss_streak,
            )
        except Exception as e:
            logger.debug("Dynamic sizing skipped: %s", e)

    effective_risk *= vix_factor
    contracts = contracts_from_risk(effective_risk, risk_pts)
    rr = (abs(setup.target1_price - setup.entry_price) / risk_pts) if risk_pts else 0

    time_est = now.strftime("%I:%M %p EST")
    tf_note = "1-min | 15-min trend: " + trend.value
    msg = format_trade_alert(
        setup_name=setup_name_label,
        time_est=time_est,
        direction=setup.direction,
        entry=setup.entry_price,
        stop=setup.stop_price,
        tp1=setup.target1_price,
        tp2=setup.target2_price,
        rr_ratio=rr,
        confidence=setup.confidence,
        timeframe_note=tf_note,
        key_level=setup.key_level_name,
        notes=setup.notes,
        contracts=contracts,
        risk_usd=effective_risk,
    )
    await send_telegram_all(msg, bot)

    if AUTO_EXECUTE:
        broker = get_broker(BROKER)
        if broker.is_connected():
            side = "BUY" if setup.direction == "LONG" else "SELL"
            res = broker.place_market_order(INSTRUMENT, side, contracts)
            if res.success and broker.__class__.__name__ == "PaperBroker":
                broker.set_fill_price(INSTRUMENT, setup.entry_price)
            if res.success:
                broker.place_stop_order(INSTRUMENT, "SELL" if setup.direction == "LONG" else "BUY", contracts, setup.stop_price)

    trade = ActiveTrade(
        direction=setup.direction,
        entry=setup.entry_price,
        stop=setup.stop_price,
        target1=setup.target1_price,
        target2=setup.target2_price,
        contracts=contracts,
        risk_per_contract_usd=risk_pts * 2.0,
    )
    state["active_trades"].append({
        "trade": trade,
        "id": len(state["active_trades"]) + 1,
        "direction": trade.direction,
        "entry": trade.entry,
        "stop": trade.current_stop,
    })
    state["trades_today"] += 1
    log_trade(setup.direction, setup.entry_price, setup.stop_price, setup.target1_price, setup.target2_price, "open", notes=setup.key_level_name)


def _run_scan_fetch_sync():
    """
    Run in thread pool: feed + candles + levels. Keeps event loop free so Telegram
    buttons and dashboard stay responsive. Returns (df_1m, df_15m, current_price,
    key_levels, swing_highs, swing_lows, trend, now) or None on failure.
    """
    try:
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        if not feed.is_connected():
            return None
        df_1m = feed.get_1m_candles(100)
        df_15m = feed.get_15m_candles(50)
        if df_1m is None or df_15m is None or df_1m.empty or df_15m.empty:
            return None
        now = now_est()
        key_levels = build_key_levels(df_15m, df_1m, now)
        swing_highs, swing_lows = swing_highs_lows(df_15m)
        trend = trend_from_structure(df_15m, swing_highs, swing_lows)
        current_price = feed.get_current_price()
        return (df_1m, df_15m, current_price, key_levels, swing_highs, swing_lows, trend, now)
    except Exception as e:
        logger.warning("Scan fetch (sync) failed: %s", e)
        return None


# Throttle "outside session" status to once per 15 min so Telegram isn't spammed
async def run_scan(bot=None):
    """Fetch data, detect setup, validate checklist, send alert and optionally execute."""
    if not bot or not TELEGRAM_CHAT_IDS:
        return
    maybe_reset_daily()
    state = get_state()
    now = now_est()
    today_iso = date.today().isoformat()

    # Day/news filter: skip Monday, CPI, FOMC, NFP (Riley Coleman best)
    tradeable, reason = should_trade_today(
        skip_monday=SKIP_MONDAY,
        skip_cpi=SKIP_CPI_DAYS,
        skip_fomc=SKIP_FOMC_DAYS,
        skip_nfp=SKIP_NFP_DAYS,
    )
    if not tradeable:
        if state.get("skip_day_alert_date") != today_iso:
            await send_telegram_all(
                f"⛔ <b>NO TRADE TODAY</b>\n\n"
                f"🚫 {reason}\n\n"
                f"📅 Next best trading day: Tuesday–Thursday\n"
                f"💤 Bot is in STANDBY mode today.",
                bot,
            )
            state["skip_day_alert_date"] = today_iso
            save_trade_state()
        return

    if not state.get("scan_active", True):
        logger.debug("Scan skipped: paused by user")
        return

    if not in_scan_window():
        return

    # Auto-start live feed (WebSocket) when session starts; keeps rest outside session
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, start_live_feed_session)
    except Exception as e:
        logger.debug("start_live_feed_session: %s", e)

    max_trades = MAX_TRADES_PER_DAY

    if state["trades_today"] >= max_trades:
        logger.debug("Scan skipped: trades_today=%d >= max=%d", state["trades_today"], max_trades)
        return

    # VIX filter: block or reduce risk on high volatility days
    vix_factor = 1.0
    if VIX_FILTER_ENABLED:
        try:
            from data.vix_filter import vix_check
            vix_result = vix_check(VIX_BLOCK_THRESHOLD, VIX_REDUCE_THRESHOLD)
            if vix_result["action"] == "block":
                logger.info("VIX filter: trading blocked (VIX=%.1f)", vix_result.get("vix", 0))
                if SHOW_SCAN_STATUS:
                    await send_telegram_all(
                        f"🔍 <b>Scan</b> {now.strftime('%I:%M %p EST')} | VIX <code>{vix_result.get('vix', 0):.0f}</code> - trading blocked (too high)",
                        bot,
                    )
                return
            elif vix_result["action"] == "reduce":
                vix_factor = vix_result.get("factor", 0.5)
        except Exception as e:
            logger.debug("VIX filter skipped: %s", e)

    if state.get("daily_pnl", 0) <= -MAX_DAILY_LOSS_USD:
        await send_telegram_all(
            f"<b>🛑 Daily loss limit</b>\n"
            f"────────────────────\n"
            f"Limit <code>${MAX_DAILY_LOSS_USD}</code> reached. Trading paused.",
            bot,
        )
        return

    # Run blocking I/O in thread pool so Telegram buttons and dashboard stay responsive
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _run_scan_fetch_sync)
    if result is None:
        if SHOW_SCAN_STATUS:
            await send_telegram_all(
                f"🔍 <b>Scan</b> {now.strftime('%I:%M %p EST')} │ Feed/candle error or no data. Check /apis.",
                bot,
            )
        await _record_scan_failure(state, bot, "Feed/candle error or no data")
        return

    df_1m, df_15m, current_price, key_levels, swing_highs, swing_lows, trend, now = result

    state["consecutive_scan_failures"] = 0
    state["scan_failure_alert_sent"] = False
    state["total_scans"] = state.get("total_scans", 0) + 1
    state["key_levels_text"] = _format_levels(key_levels)

    # Trade window 9:30–11:00 EST only; 7:00–9:29 is SCAN_ONLY (levels updated above, no signals)
    if not in_trade_window():
        save_trade_state()
        return

    # Send "MARKET OPEN" once per day when entering trade window
    if state.get("market_open_alert_date") != today_iso:
        await send_telegram_all(
            f"✅ <b>MARKET OPEN</b> — Scanning for setups\n\n"
            f"🕐 Primary window: 9:30–11:00 AM EST\n"
            f"🎯 Max trades today: {MAX_TRADES_PER_DAY}\n"
            f"💰 Risk per trade: 1%\n"
            f"📊 Min R:R required: 1:3",
            bot,
        )
        state["market_open_alert_date"] = today_iso

    await _run_single_strategy(
        bot, state, now, vix_factor, max_trades,
        df_1m, df_15m, key_levels, swing_highs, swing_lows, trend,
        current_price,
    )

    save_trade_state()


def get_levels_on_demand() -> tuple[str | None, str]:
    """Fetch candles and build key levels on demand. Returns (levels_text, error_hint). error_hint only when levels_text is None."""
    try:
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        # Fetch candles first (for Yahoo, connection is established when we fetch)
        df_1m = feed.get_1m_candles(100)
        df_15m = feed.get_15m_candles(50)
        if df_1m is None or df_15m is None or df_1m.empty or df_15m.empty:
            hint = "No 1m/15m candle data. Try during US session (7:00–11:00 AM EST) or check /apis."
            if not feed.is_connected():
                hint = "Feed not connected or no data. Check /apis or set MNQ_PRICE_API_URL."
            return None, hint
        now = now_est()
        key_levels = build_key_levels(df_15m, df_1m, now)
        return _format_levels(key_levels), ""
    except Exception as e:
        logger.debug("get_levels_on_demand failed: %s", e)
        return None, str(e) or "Unknown error"


def _count_levels(kl) -> int:
    """Number of key levels currently available (for status line)."""
    n = 0
    if kl.prev_day_high is not None: n += 1
    if kl.prev_day_low is not None: n += 1
    if kl.prev_day_close is not None: n += 1
    if kl.seven_am_high is not None: n += 1
    if kl.seven_am_low is not None: n += 1
    if kl.session_open_high is not None: n += 1
    if kl.session_open_low is not None: n += 1
    return n


def _format_levels(kl) -> str:
    lines = ["📌 Today's Key Levels\n"]
    if kl.prev_day_high is not None:
        lines.append(f"Prev Day H: {kl.prev_day_high:,.2f}")
    if kl.prev_day_low is not None:
        lines.append(f"Prev Day L: {kl.prev_day_low:,.2f}")
    if kl.prev_day_close is not None:
        lines.append(f"Prev Day C: {kl.prev_day_close:,.2f}")
    if kl.seven_am_high is not None:
        lines.append(f"7 AM H: {kl.seven_am_high:,.2f}")
    if kl.seven_am_low is not None:
        lines.append(f"7 AM L: {kl.seven_am_low:,.2f}")
    if kl.session_open_high is not None:
        lines.append(f"Session OR H: {kl.session_open_high:,.2f}")
    if kl.session_open_low is not None:
        lines.append(f"Session OR L: {kl.session_open_low:,.2f}")
    return "\n".join(lines) if len(lines) > 1 else "No levels yet."


async def _send_scan_status(
    bot,
    now,
    key_levels,
    trend,
    current_price: float | None,
    trades_today: int,
    reason: str,
) -> None:
    """Send a one-line scan status to Telegram at most every SCAN_STATUS_INTERVAL_MINUTES to avoid spamming."""
    if not SHOW_SCAN_STATUS or not bot or not TELEGRAM_CHAT_IDS:
        return
    state = get_state()
    last_sent = state.get("last_scan_status_sent_at")
    if last_sent is not None and isinstance(last_sent, (int, float)):
        try:
            last_dt = datetime.fromtimestamp(last_sent, tz=ZoneInfo("America/New_York"))
            if (now - last_dt).total_seconds() < SCAN_STATUS_INTERVAL_MINUTES * 60:
                logger.debug("Scan status throttled (next in %d min)", SCAN_STATUS_INTERVAL_MINUTES)
                return
        except Exception:
            pass
    state["last_scan_status_sent_at"] = now.timestamp()
    time_est = now.strftime("%I:%M %p EST")
    price_str = f"{current_price:,.2f}" if current_price is not None else "—"
    level_count = _count_levels(key_levels)
    msg = (
        f"🔍 <b>Scan</b> {time_est} │ NQ <code>{price_str}</code> │ "
        f"15m <code>{trend.value}</code> │ Levels: {level_count} │ "
        f"{reason} │ Trades: {trades_today}/{MAX_TRADES_PER_DAY}"
    )
    logger.info("Scan status: NQ=%s trend=%s levels=%d %s trades=%d/%d",
                price_str, trend.value, level_count, reason, trades_today, MAX_TRADES_PER_DAY)
    await send_telegram_all(msg, bot)


def _run_trailing_price_sync():
    """Run in thread: get current price for trailing. Keeps event loop responsive."""
    try:
        feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
        return feed.get_current_price() if feed.is_connected() else None
    except Exception as e:
        logger.warning("Feed error in trailing: %s", e)
        return None


async def run_trailing(bot=None):
    """Check active trades for trail milestones and stop hit. Send alerts."""
    if not bot or not TELEGRAM_CHAT_IDS:
        return
    state = get_state()
    if not TRAIL_ALERTS_ENABLED or not state.get("trail_alerts", True):
        return
    active_list = state.get("active_trades", [])
    if not active_list:
        return

    loop = asyncio.get_event_loop()
    current_price = await loop.run_in_executor(None, _run_trailing_price_sync)
    if current_price is None:
        return

    to_remove = []
    for item in active_list:
        trade: ActiveTrade = item["trade"]
        r = trade.rr_at_price(current_price)
        last_r = trade.last_trailed_r

        # Stop hit?
        if trade.direction == "LONG" and current_price <= trade.current_stop:
            to_remove.append(item)
            result_usd = trade.pnl_at_price(trade.current_stop)
            state["daily_pnl"] += result_usd
            state["trade_history"].append({"dir": trade.direction, "entry": trade.entry, "result": "stop", "pnl": result_usd, "date": now_est().strftime("%Y-%m-%d")})
            save_trade_state()
            msg = format_stop_hit(trade.direction, trade.entry, trade.current_stop, result_usd / trade.contracts, "stopped", state["daily_pnl"])
            await send_telegram_all(msg, bot)
            log_trade(trade.direction, trade.entry, trade.stop, trade.target1, trade.target2, "loss" if result_usd < 0 else "win", trade.current_stop, trade.rr_at_price(trade.current_stop))
            continue
        if trade.direction == "SHORT" and current_price >= trade.current_stop:
            to_remove.append(item)
            result_usd = trade.pnl_at_price(trade.current_stop)
            state["daily_pnl"] += result_usd
            state["trade_history"].append({"dir": trade.direction, "entry": trade.entry, "result": "stop", "pnl": result_usd, "date": now_est().strftime("%Y-%m-%d")})
            save_trade_state()
            msg = format_stop_hit(trade.direction, trade.entry, trade.current_stop, result_usd / trade.contracts, "stopped", state["daily_pnl"])
            await send_telegram_all(msg, bot)
            log_trade(trade.direction, trade.entry, trade.stop, trade.target1, trade.target2, "loss" if result_usd < 0 else "win", trade.current_stop, trade.rr_at_price(trade.current_stop))
            continue

        # New milestone?
        next_m = next_milestone_to_trail(r, last_r)
        if next_m is not None:
            new_stop = stop_for_milestone(trade, next_m)
            trade.current_stop = new_stop
            trade.last_trailed_r = next_m
            item["stop"] = new_stop
            save_trade_state()
            action = f"Move Stop Loss to +{next_m}R" if next_m == 1.0 else f"Trail stop to +{next_m - 1}R"
            tip = "Take 50% off here and let the rest run!" if next_m == 2.0 else ""
            msg = format_trail_alert(
                trade.direction,
                trade.entry,
                current_price,
                r,
                action,
                new_stop,
                f"(locks in +${trade.pnl_at_price(new_stop)/trade.contracts:.0f}/contract)",
                trade.target2,
                tip,
            )
            await send_telegram_all(msg, bot)
            if TRAIL_MODE == "auto":
                # Would call broker.update_stop(order_id, new_stop)
                pass

    for item in to_remove:
        state["active_trades"].remove(item)
    if to_remove:
        save_trade_state()
        try:
            from data.equity_tracker import record_equity
            balance = 50000.0 + state.get("daily_pnl", 0)
            record_equity(balance, state.get("daily_pnl", 0), state.get("trades_today", 0))
        except Exception as e:
            logger.debug("Equity recording failed: %s", e)


@_safe_job
async def daily_summary_job(context: ContextTypes.DEFAULT_TYPE):
    """Send daily P&L summary (called by PTB job_queue)."""
    if not context.application.bot or not TELEGRAM_CHAT_IDS:
        return
    state = get_state()
    trades = state.get("trade_history", [])
    today_trades = [t for t in trades if True]  # Could filter by date
    n = len(today_trades)
    winners = sum(1 for t in today_trades if t.get("pnl", 0) > 0)
    losers = sum(1 for t in today_trades if t.get("pnl", 0) < 0)
    pnl = state.get("daily_pnl", 0)
    wr = (100 * winners / n) if n else 0
    lines = [f"Trade {i+1}: {t.get('dir','?')} @ {t.get('entry',0):,.2f} → ${t.get('pnl',0):+.0f}" for i, t in enumerate(today_trades[-10:])]
    msg = format_daily_summary(now_est().strftime("%Y-%m-%d"), state["trades_today"], winners, losers, pnl, wr, lines)
    await send_telegram_all(msg, context.application.bot)


@_safe_job
async def scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled scan + trailing (called by PTB job_queue)."""
    global _last_heartbeat, _consecutive_job_errors
    bot = context.application.bot if context and context.application else None
    await run_scan(bot)
    await run_trailing(bot)
    _last_heartbeat = datetime.now(EST)
    _consecutive_job_errors = 0


def _send_telegram_sync(text: str, parse_mode: str = "HTML") -> None:
    """Send message to all configured Telegram chat IDs from a background thread (sync HTTP)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_IDS:
        return
    import urllib.request
    import urllib.parse
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
            data = urllib.parse.urlencode(payload).encode()
            req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=10) as r:
                pass
        except Exception as e:
            logger.warning("Telegram sync send to %s failed: %s", chat_id, e)


def _do_auto_retrain(context: ContextTypes.DEFAULT_TYPE):
    """Run training in background thread and send Telegram when done."""
    try:
        from train_for_live import run_auto_retrain
        res = run_auto_retrain(update_config=True, verbose=False)
        if res.get("success"):
            p = res.get("best_params") or {}
            msg = (
                "<b>🔄 Auto-retrain complete</b>\n"
                "────────────────────\n"
                f"risk=<code>{p.get('risk', '')}</code> tol=<code>{p.get('level_tol', '')}</code> "
                f"tp1=<code>{p.get('tp1_rr', '')}</code> tp2=<code>{p.get('tp2_rr', '')}</code> "
                f"max_t=<code>{p.get('max_trades', '')}</code> body=<code>{p.get('min_body', '')}</code>\n\n"
                f"3mo: P&L <code>${res.get('full_profit', 0):+,.0f}</code> ({res.get('total_return_pct', 0):+.2f}%) | "
                f"{res.get('total_trades', 0)} trades | WR {res.get('win_rate_pct', 0):.1f}% | DD {res.get('max_drawdown_pct', 0):.2f}%\n\n"
                "<i>Restart the bot to use new parameters.</i>"
            )
            _send_telegram_sync(msg)
        else:
            err = html.escape(str(res.get("error") or "Unknown error"))
            _send_telegram_sync(f"<b>❌ Auto-retrain failed</b>\n{err}")
    except Exception as e:
        logger.exception("Auto-retrain failed: %s", e)
        _send_telegram_sync(f"<b>❌ Auto-retrain error</b>\n{html.escape(str(e))}")


@_safe_job
async def weekly_report_job(context: ContextTypes.DEFAULT_TYPE):
    """Send weekly P&L report (called by PTB job_queue)."""
    if not context.application.bot or not TELEGRAM_CHAT_IDS:
        return
    from bot.alerts import format_weekly_report, send_telegram_all as _send_all
    state = get_state()
    history = state.get("trade_history", [])
    now = now_est()
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week_trades = [h for h in history if (h.get("date") or "") >= cutoff]
    if not week_trades:
        return
    n = len(week_trades)
    winners = sum(1 for h in week_trades if (h.get("pnl") or 0) > 0)
    losers = n - winners
    pnl = sum(h.get("pnl", 0) for h in week_trades)
    wr = (100 * winners / n) if n else 0
    pnls = [h.get("pnl", 0) for h in week_trades]
    best = max(pnls) if pnls else 0
    worst = min(pnls) if pnls else 0
    running_pnl = 0
    peak = 0
    max_dd = 0
    for p in pnls:
        running_pnl += p
        peak = max(peak, running_pnl)
        dd = peak - running_pnl
        max_dd = max(max_dd, dd)
    date_range = f"{cutoff} to {now.strftime('%Y-%m-%d')}"
    msg = format_weekly_report(date_range, n, winners, losers, pnl, wr, best, worst, max_dd)
    try:
        await _send_all(msg, context.application.bot)
    except Exception as e:
        logger.warning("Weekly report send failed: %s", e)


@_safe_job
async def retrain_job(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled auto-retrain: run training in a background thread (takes ~7+ min)."""
    if not AUTO_RETRAIN_ENABLED:
        return
    thread = threading.Thread(target=_do_auto_retrain, args=(context,), daemon=True)
    thread.start()
    logger.info("Auto-retrain started in background (runs weekly).")


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors: log Conflict as a short warning, rate-limits with sleep, others with full traceback."""
    err = context.error
    if isinstance(err, Conflict):
        logger.warning(
            "Telegram Conflict: another bot instance is using getUpdates. "
            "Stop the other instance (e.g. PythonAnywhere or another terminal). Bot will retry."
        )
        return
    if isinstance(err, RetryAfter):
        logger.warning("Telegram rate limit: retry after %s s", err.retry_after)
        await asyncio.sleep(min(err.retry_after, 60))
        return
    if isinstance(err, (NetworkError, TimedOut, OSError)):
        logger.warning("Network/timeout error (bot will retry): %s", err)
        return
    logger.error("Update %s caused error:\n%s", update, traceback.format_exc())


@_safe_job
async def session_end_feed_job(context: ContextTypes.DEFAULT_TYPE):
    """When session ends (e.g. 11:00 EST): disconnect WebSocket so feed is at rest until next session."""
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, end_live_feed_session)
    except Exception as e:
        logger.debug("session_end_feed_job: %s", e)


@_safe_job
async def heartbeat_job(context: ContextTypes.DEFAULT_TYPE):
    """Periodic health check: log status, run GC, detect stalls."""
    global _consecutive_job_errors
    maybe_reset_daily()
    now = datetime.now(EST)
    state = get_state()
    active = len(state.get("active_trades", []))
    scans = state.get("total_scans", 0)
    logger.info(
        "Heartbeat %s | scans=%d active_trades=%d daily_pnl=$%.0f trades_today=%d last_scan=%s",
        now.strftime("%H:%M EST"), scans, active, state.get("daily_pnl", 0),
        state.get("trades_today", 0),
        _last_heartbeat.strftime("%H:%M") if _last_heartbeat else "never",
    )
    gc.collect()


async def _post_init(app: Application) -> None:
    """Notify users on startup with user-friendly dashboard (risk, P&L, win/loss, session)."""
    from bot import format_welcome_message
    welcome = "<b>🟢 Bot online</b>\n\n" + format_welcome_message()
    for cid in TELEGRAM_CHAT_IDS:
        try:
            await app.bot.send_message(
                chat_id=cid,
                text=welcome,
                parse_mode="HTML",
            )
        except Exception:
            pass


def _build_app() -> Application:
    """Create the PTB Application with all handlers and jobs."""
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )
    app.add_error_handler(_error_handler)
    register_commands(app)

    app.job_queue.run_repeating(scan_job, interval=60, first=10)
    app.job_queue.run_daily(daily_summary_job, time=time(11, 0, tzinfo=EST))
    # Auto-disconnect live feed (WebSocket) when session ends — rest until next session
    _session_end_time = _parse_session_end_time()
    app.job_queue.run_daily(session_end_feed_job, time=_session_end_time)
    logger.info("Session feed control: WebSocket on when session starts, rest at %s EST", _session_end_time.strftime("%H:%M"))
    app.job_queue.run_repeating(heartbeat_job, interval=300, first=60)

    if AUTO_RETRAIN_ENABLED and app.job_queue:
        warnings.filterwarnings("ignore", category=PTBUserWarning, message=".*days.*cron.*")
        app.job_queue.run_daily(
            retrain_job,
            time=time(RETRAIN_HOUR_EST, RETRAIN_MINUTE_EST, tzinfo=EST),
            days=(RETRAIN_DAY_OF_WEEK,),
        )
        logger.info("Auto-retrain scheduled: day=%s %02d:%02d EST", RETRAIN_DAY_OF_WEEK, RETRAIN_HOUR_EST, RETRAIN_MINUTE_EST)

    app.job_queue.run_daily(
        weekly_report_job,
        time=time(WEEKLY_REPORT_HOUR, 0, tzinfo=EST),
        days=(WEEKLY_REPORT_DAY,),
    )
    logger.info("Weekly report scheduled: day=%s %02d:00 EST", WEEKLY_REPORT_DAY, WEEKLY_REPORT_HOUR)

    return app


def _start_realtime_collectors():
    """Start Alpaca/Finnhub real-time data collectors if configured."""
    if not REALTIME_ORDERFLOW_ENABLED:
        logger.info("Real-time order flow disabled (MNQ_REALTIME_ORDERFLOW=false)")
        return
    try:
        from data.realtime_collector import get_collector_manager
        mgr = get_collector_manager()
        desc = mgr.start(
            alpaca_key=ALPACA_DATA_API_KEY,
            alpaca_secret=ALPACA_DATA_SECRET_KEY,
            finnhub_key=FINNHUB_API_KEY,
        )
        logger.info("Real-time data: %s", desc)
    except Exception as e:
        logger.warning("Could not start real-time collectors: %s", e)


def main():
    setup_logging()
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (env or config) to run the bot.")
        sys.exit(1)

    # Start real-time order flow collectors (Alpaca/Finnhub WebSocket)
    _start_realtime_collectors()

    max_retries = 0  # unlimited
    retry_delay = 5  # seconds, grows with back-off
    attempt = 0

    while True:
        attempt += 1
        try:
            logger.info(
                "MNQ Bot v2.3 starting (attempt %d) – Riley Coleman. Signals only %s.",
                attempt, SCAN_SESSION_EST,
            )
            app = _build_app()
            app.run_polling(
                drop_pending_updates=False,
            )
            logger.info("Bot polling stopped cleanly.")
            break  # clean shutdown (e.g. Ctrl+C)

        except (NetworkError, TimedOut, OSError, ConnectionError) as e:
            logger.warning("Bot disconnected (%s). Restarting in %ds…", e, retry_delay)
            import time as _time
            _time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 120)

        except Conflict:
            logger.error(
                "Another bot instance is running (Conflict). "
                "Waiting 30s then retrying…"
            )
            import time as _time
            _time.sleep(30)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user (Ctrl+C).")
            break

        except Exception:
            logger.critical("Fatal error – restarting in %ds:\n%s", retry_delay, traceback.format_exc())
            import time as _time
            _time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 120)


if __name__ == "__main__":
    main()
