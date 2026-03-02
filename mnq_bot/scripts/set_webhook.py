"""Set Telegram webhook URL (run once after deploying to PythonAnywhere)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import TELEGRAM_BOT_TOKEN

def main():
    url = os.getenv("WEBHOOK_URL", "").strip()
    if not url:
        print("Set WEBHOOK_URL to your full webhook URL, e.g.:")
        print("  export WEBHOOK_URL=https://YOURUSER.pythonanywhere.com/webhook")
        print("  python scripts/set_webhook.py")
        sys.exit(1)
    if not url.endswith("/webhook"):
        url = url.rstrip("/") + "/webhook"
    if not TELEGRAM_BOT_TOKEN:
        print("Set TELEGRAM_BOT_TOKEN in environment or .env")
        sys.exit(1)
    import urllib.request
    import urllib.parse
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    data = urllib.parse.urlencode({"url": url}).encode()
    req = urllib.request.Request(api, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        out = r.read().decode()
    print("Response:", out)

if __name__ == "__main__":
    main()
