"""
MNQ Bot - SINGLE FILE for PythonAnywhere.
Save this file in: /home/YOUR_USERNAME/nasdaq100bott/mnq_bot/run_bot_pa.py

In Web tab → WSGI configuration file: replace content with only this (2 lines):
  import sys
  sys.path.insert(0, '/home/ahazm3333/nasdaq100bott/mnq_bot')
  from run_bot_pa import application

Then Reload the web app. Bot is running.
Set env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CRON_SECRET.
Schedule every minute: https://ahazm3333.pythonanywhere.com/cron/scan?secret=YOUR_CRON_SECRET
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from flask import Flask, request, Response
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot import register_commands
from telegram import Update
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

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return Response("Bad request", status=400)
        ptb = get_ptb_app()
        update = Update.de_json(data, ptb.bot)
        asyncio.run(ptb.process_update(update))
        return Response("OK", status=200)
    except Exception as e:
        return Response("Error", status=500)

@app.route("/cron/scan", methods=["GET", "POST"])
def cron_scan():
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
        return Response("Error", status=500)

@app.route("/")
def index():
    return "MNQ Bot is running. /webhook for Telegram, /cron/scan for scan.", 200

# WSGI expects "application"
application = app
