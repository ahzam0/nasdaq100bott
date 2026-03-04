"""
MNQ Trading Bot – Riley Coleman Strategy
Entry point: Telegram bot + scan loop + trailing alerts + daily summary.
"""

from __future__ import annotations

import html
import logging
import sys
import threading
import warnings
from datetime import time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Ensure project root on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (
    AUTO_EXECUTE,
    BROKER,
    INSTRUMENT,
    USE_LIVE_FEED,
    PRICE_API_URL,
    USE_ORDERFLOW,
    ORDERFLOW_API_URL,
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
    SHOW_SCAN_STATUS,
    TRAIL_ALERTS_ENABLED,
    TRAIL_MODE,
    TARGET_MIN_TRADES_PER_DAY,
    FALLBACK_AFTER_MINUTES,
    FALLBACK_MIN_RR,
    AUTO_RETRAIN_ENABLED,
    RETRAIN_DAY_OF_WEEK,
    RETRAIN_HOUR_EST,
    RETRAIN_MINUTE_EST,
    SCAN_SESSION_EST,
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
    format_trade_alert,
    format_trail_alert,
    format_stop_hit,
    format_daily_summary,
    send_telegram,
    now_est,
    in_scan_window,
)
from broker import get_broker
from utils import setup_logging, log_trade, contracts_from_risk

from telegram.error import Conflict
from telegram.ext import Application, ContextTypes
from telegram.warnings import PTBUserWarning

logger = logging.getLogger(__name__)
EST = ZoneInfo("America/New_York")


def _fetch_orderflow_summary(timeout_sec: float = 2.0) -> dict | None:
    """Fetch live order flow summary from our API. Returns None on failure or timeout."""
    if not ORDERFLOW_API_URL:
        return None
    try:
        import urllib.request
        url = ORDERFLOW_API_URL.rstrip("/") + "/orderflow/summary"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout_sec) as r:
            import json
            return json.loads(r.read().decode())
    except Exception as e:
        if USE_ORDERFLOW:
            logger.warning("Order flow fetch failed (check ORDERFLOW_API_URL and server): %s", e)
        else:
            logger.debug("Order flow fetch failed: %s", e)
        return None


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
        await send_telegram(msg, bot, TELEGRAM_CHAT_ID)


# Throttle "outside session" status to once per 15 min so Telegram isn't spammed
OUTSIDE_SESSION_STATUS_INTERVAL_MIN = 15


async def run_scan(bot=None):
    """Fetch data, detect setup, validate checklist, send alert and optionally execute."""
    if not bot or not TELEGRAM_CHAT_ID:
        return
    state = get_state()
    if not state.get("scan_active", True):
        return
    now = now_est()

    if not in_scan_window():
        # Outside session: send a visible "bot running" status (throttled)
        if SHOW_SCAN_STATUS:
            last = state.get("last_idle_status_sent")
            if last is None or (now - last) >= timedelta(minutes=OUTSIDE_SESSION_STATUS_INTERVAL_MIN):
                await send_telegram(
                    f"⏸ <b>Bot running</b> │ Signals only <code>{SCAN_SESSION_EST}</code>. "
                    f"Next scan when in session.",
                    bot,
                    TELEGRAM_CHAT_ID,
                )
                state["last_idle_status_sent"] = now
        return

    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        return
    if state.get("daily_pnl", 0) <= -MAX_DAILY_LOSS_USD:
        await send_telegram(
            f"<b>🛑 Daily loss limit</b>\n"
            f"────────────────────\n"
            f"Limit <code>${MAX_DAILY_LOSS_USD}</code> reached. Trading paused.",
            bot,
            TELEGRAM_CHAT_ID,
        )
        return

    feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
    if not feed.is_connected():
        if SHOW_SCAN_STATUS:
            await send_telegram(
                f"🔍 <b>Scan</b> {now.strftime('%I:%M %p EST')} │ Feed not connected. Check /apis.",
                bot,
                TELEGRAM_CHAT_ID,
            )
        _record_scan_failure(state, bot, "Feed not connected")
        return
    try:
        df_1m = feed.get_1m_candles(100)
        df_15m = feed.get_15m_candles(50)
    except Exception as e:
        logger.warning("Feed error: %s", e)
        if SHOW_SCAN_STATUS:
            await send_telegram(
                f"🔍 <b>Scan</b> {now.strftime('%I:%M %p EST')} │ Error: {html.escape(str(e))}",
                bot,
                TELEGRAM_CHAT_ID,
            )
        _record_scan_failure(state, bot, str(e))
        return
    if df_1m.empty or df_15m.empty:
        if SHOW_SCAN_STATUS:
            await send_telegram(
                f"🔍 <b>Scan</b> {now.strftime('%I:%M %p EST')} │ No candle data (try during 7:00–11:00 AM EST).",
                bot,
                TELEGRAM_CHAT_ID,
            )
        _record_scan_failure(state, bot, "No candle data")
        return

    state["consecutive_scan_failures"] = 0
    state["scan_failure_alert_sent"] = False
    state["total_scans"] = state.get("total_scans", 0) + 1
    key_levels = build_key_levels(df_15m, df_1m, now)
    state["key_levels_text"] = _format_levels(key_levels)

    swing_highs, swing_lows = swing_highs_lows(df_15m)
    trend = trend_from_structure(df_15m, swing_highs, swing_lows)
    current_price = feed.get_current_price()

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

    risk_pts = abs(setup.entry_price - setup.stop_price)
    if MAX_RISK_PTS is not None and risk_pts > MAX_RISK_PTS:
        await _send_scan_status(bot, now, key_levels, trend, current_price, state["trades_today"], "No setup (stop too wide)")
        return  # Skip wide-stop setups (match backtest; keeps DD low)

    # Minimum 1 trade/day: after 10:30 EST if 0 trades, use slightly relaxed min R:R (still quality)
    mins_since_7 = (now.hour - 7) * 60 + now.minute if 7 <= now.hour < 12 else 0
    use_fallback_rr = (
        TARGET_MIN_TRADES_PER_DAY >= 1
        and FALLBACK_AFTER_MINUTES > 0
        and FALLBACK_MIN_RR is not None
        and state["trades_today"] == 0
        and mins_since_7 >= FALLBACK_AFTER_MINUTES
    )
    min_rr_use = FALLBACK_MIN_RR if use_fallback_rr else MIN_RR_RATIO

    orderflow_summary = None
    use_orderflow_effective = state.get("use_orderflow", USE_ORDERFLOW)
    if use_orderflow_effective and ORDERFLOW_API_URL:
        orderflow_summary = _fetch_orderflow_summary()
        if orderflow_summary is not None:
            state["last_orderflow_summary"] = orderflow_summary

    result = validate_entry(
        setup, now, state["trades_today"], MAX_TRADES_PER_DAY,
        min_rr_ratio=min_rr_use,
        orderflow_summary=orderflow_summary,
    )
    if not result.valid:
        logger.info("Entry rejected: %s", result.reason)
        await _send_scan_status(bot, now, key_levels, trend, current_price, state["trades_today"], f"Rejected: {result.reason}")
        return

    contracts = contracts_from_risk(state["risk_per_trade"], risk_pts)
    rr = (abs(setup.target1_price - setup.entry_price) / risk_pts) if risk_pts else 0

    time_est = now.strftime("%I:%M %p EST")
    msg = format_trade_alert(
        setup_name=setup.setup_type.value,
        time_est=time_est,
        direction=setup.direction,
        entry=setup.entry_price,
        stop=setup.stop_price,
        tp1=setup.target1_price,
        tp2=setup.target2_price,
        rr_ratio=rr,
        confidence=setup.confidence,
        timeframe_note="1-min | 15-min trend: " + trend.value,
        key_level=setup.key_level_name,
        notes=setup.notes,
    )
    await send_telegram(msg, bot, TELEGRAM_CHAT_ID)

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
    """Send a one-line scan status to Telegram so users see what the bot is doing."""
    if not SHOW_SCAN_STATUS or not bot or not TELEGRAM_CHAT_ID:
        return
    time_est = now.strftime("%I:%M %p EST")
    price_str = f"{current_price:,.2f}" if current_price is not None else "—"
    level_count = _count_levels(key_levels)
    msg = (
        f"🔍 <b>Scan</b> {time_est} │ NQ <code>{price_str}</code> │ "
        f"15m <code>{trend.value}</code> │ Levels: {level_count} │ "
        f"{reason} │ Trades: {trades_today}/{MAX_TRADES_PER_DAY}"
    )
    await send_telegram(msg, bot, TELEGRAM_CHAT_ID)


async def run_trailing(bot=None):
    """Check active trades for trail milestones and stop hit. Send alerts."""
    if not bot or not TELEGRAM_CHAT_ID:
        return
    state = get_state()
    if not TRAIL_ALERTS_ENABLED or not state.get("trail_alerts", True):
        return
    active_list = state.get("active_trades", [])
    if not active_list:
        return

    feed = get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)
    current_price = feed.get_current_price() if feed.is_connected() else None
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
            await send_telegram(msg, bot, TELEGRAM_CHAT_ID)
            log_trade(trade.direction, trade.entry, trade.stop, trade.target1, trade.target2, "loss" if result_usd < 0 else "win", trade.current_stop, trade.rr_at_price(trade.current_stop))
            continue
        if trade.direction == "SHORT" and current_price >= trade.current_stop:
            to_remove.append(item)
            result_usd = trade.pnl_at_price(trade.current_stop)
            state["daily_pnl"] += result_usd
            state["trade_history"].append({"dir": trade.direction, "entry": trade.entry, "result": "stop", "pnl": result_usd, "date": now_est().strftime("%Y-%m-%d")})
            save_trade_state()
            msg = format_stop_hit(trade.direction, trade.entry, trade.current_stop, result_usd / trade.contracts, "stopped", state["daily_pnl"])
            await send_telegram(msg, bot, TELEGRAM_CHAT_ID)
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
            await send_telegram(msg, bot, TELEGRAM_CHAT_ID)
            if TRAIL_MODE == "auto":
                # Would call broker.update_stop(order_id, new_stop)
                pass

    for item in to_remove:
        state["active_trades"].remove(item)
    if to_remove:
        save_trade_state()


async def daily_summary_job(context: ContextTypes.DEFAULT_TYPE):
    """Send daily P&L summary (called by PTB job_queue)."""
    if not context.application.bot or not TELEGRAM_CHAT_ID:
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
    await send_telegram(msg, context.application.bot, TELEGRAM_CHAT_ID)


async def scan_job(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled scan + trailing (called by PTB job_queue)."""
    bot = context.application.bot if context and context.application else None
    await run_scan(bot)
    await run_trailing(bot)


def _send_telegram_sync(text: str, parse_mode: str = "HTML") -> None:
    """Send message to Telegram from a background thread (sync HTTP)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": parse_mode}
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=10) as r:
            pass
    except Exception as e:
        logger.warning("Telegram sync send failed: %s", e)


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
                f"Params: risk=<code>{p.get('risk', '')}</code> min_rr=<code>{p.get('min_rr', '')}</code> "
                f"level_tol=<code>{p.get('level_tol', '')}</code> max_rp=<code>{p.get('max_rp', '')}</code>\n\n"
                f"3mo backtest: P&L <code>${res.get('full_profit', 0):+,.0f}</code> ({res.get('total_return_pct', 0):+.2f}%) | "
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


async def retrain_job(context: ContextTypes.DEFAULT_TYPE):
    """Scheduled auto-retrain: run training in a background thread (takes ~7+ min)."""
    if not AUTO_RETRAIN_ENABLED:
        return
    thread = threading.Thread(target=_do_auto_retrain, args=(context,), daemon=True)
    thread.start()
    logger.info("Auto-retrain started in background (runs weekly).")


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors: log Conflict as a short warning, others with full traceback."""
    if isinstance(context.error, Conflict):
        logger.warning(
            "Telegram Conflict: another bot instance is using getUpdates. "
            "Stop the other instance (e.g. PythonAnywhere or another terminal). Bot will retry."
        )
        return
    logger.exception("Update %s caused error: %s", update, context.error)


def main():
    setup_logging()
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (env or config) to run the bot.")
        sys.exit(1)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_error_handler(_error_handler)
    register_commands(app)
    # Scan + trailing every 60 seconds; daily summary at 11:00 AM EST
    app.job_queue.run_repeating(scan_job, interval=60)
    app.job_queue.run_daily(daily_summary_job, time=time(11, 0, tzinfo=EST))
    # Auto-retrain weekly (e.g. Sunday 8 PM EST); runs in background thread (PTB v20+ days=cron: 0=Sun..6=Sat)
    if AUTO_RETRAIN_ENABLED and app.job_queue:
        warnings.filterwarnings("ignore", category=PTBUserWarning, message=".*days.*cron.*")
        app.job_queue.run_daily(
            retrain_job,
            time=time(RETRAIN_HOUR_EST, RETRAIN_MINUTE_EST, tzinfo=EST),
            days=(RETRAIN_DAY_OF_WEEK,),
        )
        logger.info("Auto-retrain scheduled: day=%s %02d:%02d EST", RETRAIN_DAY_OF_WEEK, RETRAIN_HOUR_EST, RETRAIN_MINUTE_EST)
    logger.info("MNQ Bot starting – Riley Coleman strategy. Signals only %s.", SCAN_SESSION_EST)
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
