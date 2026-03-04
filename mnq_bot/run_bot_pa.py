"""
MNQ Bot - ONE FILE. Click "Run" = Reload the web app (see below).

HOW TO START THE BOT (PythonAnywhere):
  1. Web tab → your web app
  2. Click the green "Reload" button
  That's it. The bot is now running (this file is the app).

First-time setup:
  - WSGI file content:  sys.path.insert(0, '/home/YOUR_USERNAME/nasdaq100bott/mnq_bot')
                        from run_bot_pa import application
  - Env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CRON_SECRET
  - Task every minute: https://YOUR_USERNAME.pythonanywhere.com/cron/scan?secret=CRON_SECRET
"""
from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Fallbacks so bot works on PythonAnywhere without setting env in dashboard (override with env if you prefer)
if not os.environ.get("TELEGRAM_BOT_TOKEN"):
    os.environ["TELEGRAM_BOT_TOKEN"] = "8510793606:AAE553KsIe0E6rAskRN-fUqM0H57_UN92zY"
if not os.environ.get("TELEGRAM_CHAT_ID"):
    os.environ["TELEGRAM_CHAT_ID"] = "8309667442"
if not os.environ.get("CRON_SECRET"):
    os.environ["CRON_SECRET"] = "mnqbotcron123"

from flask import Flask, request, Response, redirect
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, get_use_yahoo_ws_realtime, set_use_yahoo_ws_realtime
from bot import register_commands
from telegram import Bot, Update
from telegram.ext import Application

app = Flask(__name__)
_ptb_app = None

def get_ptb_app():
    global _ptb_app
    if _ptb_app is None:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        _ptb_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        register_commands(_ptb_app)
    return _ptb_app

async def _handle_webhook_update(data: dict):
    """Create a fresh Application, initialize it, process the update, then shutdown (required by PTB for webhook)."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    register_commands(app)
    await app.initialize()
    try:
        update = Update.de_json(data, app.bot)
        await app.process_update(update)
    finally:
        await app.shutdown()


@app.route("/webhook", methods=["POST"])
def webhook():
    import logging
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return Response("Bad request", status=400)
        asyncio.run(_handle_webhook_update(data))
        return Response("OK", status=200)
    except Exception as e:
        logging.exception("Webhook error")
        return Response("Error", status=500)

async def _run_scan_with_fresh_bot():
    """Run scan + trailing + daily summary using a Bot created in this event loop (avoids 'Event loop is closed')."""
    bot = Bot(TELEGRAM_BOT_TOKEN)
    import main
    await main.run_scan(bot)
    await main.run_trailing(bot)
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
        await daily_summary_job(Ctx())


@app.route("/cron/scan", methods=["GET", "POST"])
def cron_scan():
    secret = os.getenv("CRON_SECRET", "").strip()
    if secret and request.args.get("secret") != secret:
        return Response("Forbidden", status=403)
    try:
        from utils import setup_logging
        setup_logging()
        asyncio.run(_run_scan_with_fresh_bot())
        return Response("OK", status=200)
    except Exception as e:
        return Response("Error", status=500)

def _settings_secret_ok():
    secret = os.getenv("CRON_SECRET", "").strip()
    return secret and request.args.get("secret") == secret


@app.route("/")
def index():
    return "MNQ Bot is running. /webhook for Telegram, /cron/scan for scan. Visit /set-webhook once to register. Settings: /settings?secret=YOUR_CRON_SECRET", 200


@app.route("/settings", methods=["GET"])
def settings_page():
    """Settings page: toggle Yahoo WebSocket (live price) on/off. Requires ?secret=CRON_SECRET."""
    if not _settings_secret_ok():
        return Response("Forbidden. Add ?secret=YOUR_CRON_SECRET", status=403)
    try:
        yahoo_ws_on = get_use_yahoo_ws_realtime()
    except Exception:
        yahoo_ws_on = False
    status = "On" if yahoo_ws_on else "Off"
    toggle_url = lambda e: f"/settings/yahoo-ws?secret={request.args.get('secret', '')}&enabled={1 if e else 0}"
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
    """Set Yahoo WebSocket on (enabled=1) or off (enabled=0). Redirects to /settings."""
    if not _settings_secret_ok():
        return Response("Forbidden. Add ?secret=YOUR_CRON_SECRET", status=403)
    enabled = request.args.get("enabled", "").strip() in ("1", "true", "yes")
    try:
        set_use_yahoo_ws_realtime(enabled)
    except Exception as e:
        return Response(f"Error saving: {e}", status=500)
    secret = request.args.get("secret", "")
    return redirect(f"/settings?secret={secret}")


@app.route("/set-webhook", methods=["GET"])
def set_webhook_route():
    """Visit this URL once after deploy (e.g. https://your-app.up.railway.app/set-webhook?secret=mnqbotcron123)."""
    secret = os.getenv("CRON_SECRET", "").strip()
    if secret and request.args.get("secret") != secret:
        return Response("Forbidden. Add ?secret=YOUR_CRON_SECRET", status=403)
    try:
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme) or "https"
        host = request.headers.get("X-Forwarded-Host", request.host) or request.host
        base = f"{scheme}://{host}".rstrip("/")
        webhook_url = f"{base}/webhook"
        import urllib.request
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"url": webhook_url}).encode(), method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read().decode()
        return Response(f"Webhook set to {webhook_url}\n{body}", status=200, mimetype="text/plain")
    except Exception as e:
        return Response(f"Error: {e}", status=500, mimetype="text/plain")


def _run_scan_once():
    """Run scan + trailing + daily summary (same as /cron/scan). Uses fresh Bot in this loop to avoid 'Event loop is closed'."""
    try:
        from utils import setup_logging
        setup_logging()
        asyncio.run(_run_scan_with_fresh_bot())
    except Exception:
        pass


def _scheduler_loop():
    """Background: run scan every 60 seconds so you don't need external cron."""
    time.sleep(10)
    while True:
        try:
            _run_scan_once()
        except Exception:
            pass
        time.sleep(60)


# Start in-app scheduler (no need for cron-job.org or Railway cron)
_scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
_scheduler_thread.start()

# WSGI expects "application"
application = app

if __name__ == "__main__":
    # Run locally: python run_bot_pa.py (on PythonAnywhere use Web tab Reload instead)
    port = int(os.environ.get("PORT", 5000))
    application.run(host="0.0.0.0", port=port)
