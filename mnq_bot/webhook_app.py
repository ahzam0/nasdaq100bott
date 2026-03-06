"""
MNQ Bot – Webhook entry point for PythonAnywhere (and any WSGI host).
Telegram sends updates to POST /webhook. Use Scheduled Task to hit /cron/scan every minute.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

# Project root on path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from flask import Flask, request, Response, redirect

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_use_yahoo_ws_realtime, set_use_yahoo_ws_realtime
from bot import register_commands
from telegram import Update
from telegram.ext import Application

logger = logging.getLogger(__name__)
app = Flask(__name__)

# Lazy-built PTB Application (shared for webhook and cron)
_ptb_app: Application | None = None


def get_ptb_app() -> Application:
    global _ptb_app
    if _ptb_app is None:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in environment.")
        _ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        register_commands(_ptb_app)
    return _ptb_app


async def _process_webhook_update(data: dict):
    """Initialize PTB app, process update, shutdown. Required for webhook mode."""
    ptb = get_ptb_app()
    await ptb.initialize()
    try:
        update = Update.de_json(data, ptb.bot)
        await ptb.process_update(update)
    finally:
        await ptb.shutdown()


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive Telegram updates and process with PTB."""
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return Response("Bad request", status=400)
        asyncio.run(_process_webhook_update(data))
        return Response("OK", status=200)
    except Exception as e:
        logger.exception("Webhook error: %s", e)
        return Response("Error", status=500)


@app.route("/cron/scan", methods=["GET", "POST"])
def cron_scan():
    """Run scan + trailing (call every minute from PythonAnywhere Scheduled Task)."""
    secret = os.getenv("CRON_SECRET", "").strip()
    if secret and request.args.get("secret") != secret:
        return Response("Forbidden", status=403)
    try:
        from utils import setup_logging
        setup_logging()
        import main
        ptb = get_ptb_app()
        bot = ptb.bot
        asyncio.run(main.run_scan(bot))
        asyncio.run(main.run_trailing(bot))
        # Daily summary: if it's 11:00 AM EST, run summary (optional)
        from bot.scheduler import now_est
        from config import DAILY_SUMMARY_HOUR
        now = now_est()
        if now.hour == DAILY_SUMMARY_HOUR and now.minute < 2:
            from main import daily_summary_job
            class Ctx:
                class App:
                    pass
                application = App()
                application.bot = bot
            asyncio.run(daily_summary_job(Ctx()))
        return Response("OK", status=200)
    except Exception as e:
        logger.exception("Cron scan error: %s", e)
        return Response("Error", status=500)


def _settings_secret_ok():
    secret = os.getenv("CRON_SECRET", "").strip()
    return secret and request.args.get("secret") == secret


@app.route("/")
def index():
    return (
        "MNQ Bot webhook is running. Use /webhook for Telegram. "
        "Visit /set-webhook once after deploy to register with Telegram. "
        "Settings: /settings?secret=YOUR_CRON_SECRET"
    ), 200


@app.route("/set-webhook", methods=["GET"])
def set_webhook_route():
    """Call once after deploy so Telegram sends updates to this server (e.g. https://your-app.com/set-webhook?secret=CRON_SECRET)."""
    secret = os.environ.get("CRON_SECRET", "").strip()
    if secret and request.args.get("secret") != secret:
        return Response("Forbidden. Add ?secret=YOUR_CRON_SECRET", status=403)
    try:
        import urllib.request
        import urllib.parse
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme) or "https"
        host = request.headers.get("X-Forwarded-Host", request.host) or request.host
        base = f"{scheme}://{host}".rstrip("/")
        webhook_url = f"{base}/webhook"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode({"url": webhook_url}).encode(),
            method="POST",
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
        return Response(f"Webhook set to {webhook_url}\n{body}", status=200, mimetype="text/plain")
    except Exception as e:
        logger.exception("Set webhook error: %s", e)
        return Response(f"Error: {e}", status=500, mimetype="text/plain")


@app.route("/settings", methods=["GET"])
def settings_page():
    if not _settings_secret_ok():
        return Response("Forbidden. Add ?secret=YOUR_CRON_SECRET", status=403)
    try:
        yahoo_ws_on = get_use_yahoo_ws_realtime()
    except Exception:
        yahoo_ws_on = False
    status = "On" if yahoo_ws_on else "Off"
    secret = request.args.get("secret", "")
    toggle_url = lambda e: f"/settings/yahoo-ws?secret={secret}&enabled={1 if e else 0}"
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>MNQ Bot Settings</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.25rem; }}
  .card {{ background: #f5f5f5; border-radius: 8px; padding: 1rem; margin: 1rem 0; }}
  .row {{ display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.5rem; }}
  .label {{ font-weight: 500; }}
  .badge {{ padding: 0.2rem 0.5rem; border-radius: 4px; font-size: 0.9rem; }}
  .badge.on {{ background: #22c55e; color: #fff; }}
  .badge.off {{ background: #94a3b8; color: #fff; }}
  a.btn {{ display: inline-block; padding: 0.5rem 1rem; border-radius: 6px; text-decoration: none; font-weight: 500; margin-right: 0.5rem; margin-top: 0.5rem; }}
  a.btn.on {{ background: #22c55e; color: #fff; }}
  a.btn.off {{ background: #64748b; color: #fff; }}
  a.btn:hover {{ opacity: 0.9; }}
  p.hint {{ color: #64748b; font-size: 0.875rem; margin-top: 0.5rem; }}
</style>
</head>
<body>
  <h1>MNQ Bot Settings</h1>
  <div class="card">
    <div class="row">
      <span class="label">Yahoo WebSocket (live price)</span>
      <span class="badge {'on' if yahoo_ws_on else 'off'}">{status}</span>
    </div>
    <p class="hint">Minimal-delay price stream. Turn Off if the bot hits &quot;can't start new thread&quot; on Railway.</p>
    <div>
      <a class="btn on" href="{toggle_url(True)}">Turn On</a>
      <a class="btn off" href="{toggle_url(False)}">Turn Off</a>
    </div>
  </div>
  <p><a href="/">Back</a></p>
</body>
</html>"""
    return Response(html, status=200, mimetype="text/html")


@app.route("/settings/yahoo-ws", methods=["GET"])
def settings_yahoo_ws():
    if not _settings_secret_ok():
        return Response("Forbidden. Add ?secret=YOUR_CRON_SECRET", status=403)
    enabled = request.args.get("enabled", "").strip() in ("1", "true", "yes")
    try:
        set_use_yahoo_ws_realtime(enabled)
    except Exception as e:
        return Response(f"Error saving: {e}", status=500)
    secret = request.args.get("secret", "")
    return redirect(f"/settings?secret={secret}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
