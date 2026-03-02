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

from flask import Flask, request, Response

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
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


@app.route("/webhook", methods=["POST"])
def webhook():
    """Receive Telegram updates and process with PTB."""
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return Response("Bad request", status=400)
        ptb = get_ptb_app()
        update = Update.de_json(data, ptb.bot)
        asyncio.run(ptb.process_update(update))
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


@app.route("/")
def index():
    return "MNQ Bot webhook is running. Use /webhook for Telegram.", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
