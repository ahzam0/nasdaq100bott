# Set up MNQ Bot on PythonAnywhere

The bot uses **webhooks** on PythonAnywhere (no long-running polling). Telegram sends updates to your app; a **Scheduled Task** runs the scan every minute.

---

## 1. Create account and get a subdomain

- Sign up at [pythonanywhere.com](https://www.pythonanywhere.com) (free tier is fine).
- Note your username (e.g. `ahzam0`). Your app URL will be:  
  `https://ahzam0.pythonanywhere.com`

---

## 2. Clone the repo and set up the project

In the **Consoles** tab, open a **Bash** console, then:

```bash
# Clone (use your repo URL)
git clone https://github.com/ahzam0/nasdaq100bott.git
cd nasdaq100bott/mnq_bot

# Create virtualenv (Python 3.10+)
python3.10 -m venv venv
source venv/bin/activate   # On Windows host: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## 3. Set environment variables

In the PythonAnywhere **Dashboard**:

1. Go to **Account** → **Environment variables** (or the **Web** tab → your app → **Environment variables**).
2. Add:

| Name | Value |
|------|--------|
| `TELEGRAM_BOT_TOKEN` | Your bot token (from @BotFather) |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID (e.g. 8309667442) |
| `CRON_SECRET` | A random string (e.g. `mySecretCron123`) for protecting the cron URL |

Do **not** put these in the repo. Only in PythonAnywhere’s environment.

---

## 4. Create the Web app and point it to the webhook

1. Open the **Web** tab.
2. Click **Add a new web app** → choose **Flask** → **Python 3.10** (or your venv Python).
3. Set the **Project directory** (or **Source code**) to:  
   `nasdaq100bott/mnq_bot`  
   (or the full path, e.g. `/home/ahzam0/nasdaq100bott/mnq_bot`).
4. **WSGI configuration**:  
   Click the WSGI file link and edit it so it loads the webhook app.

Replace the file content with something like (adjust paths to your username):

```python
import sys
path = '/home/YOUR_USERNAME/nasdaq100bott/mnq_bot'
if path not in sys.path:
    sys.path.insert(0, path)

# Load .env from project dir if present
import os
from dotenv import load_dotenv
load_dotenv(os.path.join(path, '.env'))

from webhook_app import app as application
```

Replace `YOUR_USERNAME` with your PythonAnywhere username. Save the file.

5. In the **Web** tab, set **Virtualenv** to your project venv, e.g.:  
   `/home/YOUR_USERNAME/nasdaq100bott/mnq_bot/venv`
6. Click **Reload** for the web app.

Your app should be live at:  
`https://YOUR_USERNAME.pythonanywhere.com`

---

## 5. Set the Telegram webhook

Tell Telegram to send updates to your app (run **once** after the web app is working).

**Option A – From your PC (with token and URL):**

```bash
cd mnq_bot
export TELEGRAM_BOT_TOKEN="your_bot_token"
export WEBHOOK_URL="https://YOUR_USERNAME.pythonanywhere.com/webhook"
python scripts/set_webhook.py
```

**Option B – With curl:**

```bash
curl -F "url=https://YOUR_USERNAME.pythonanywhere.com/webhook" \
  "https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook"
```

Replace `YOUR_USERNAME` and `YOUR_BOT_TOKEN`. After this, Telegram will POST updates to `/webhook`.

---

## 6. Run the scan every minute (Scheduled Task)

The bot needs the **scan** (and trailing) to run every minute. Use a **Scheduled Task** that calls your app.

1. In the **Dashboard**, open **Tasks** (or the **Schedule** tab).
2. Create a new scheduled task:
   - **Time**: every minute (e.g. `* * * * *` in cron, or use the “Every minute” option if available).
   - **Command** (choose one):

**If PythonAnywhere allows “Run a URL”:**

- URL:  
  `https://YOUR_USERNAME.pythonanywhere.com/cron/scan?secret=YOUR_CRON_SECRET`  
  Use the same `CRON_SECRET` you set in step 3.

**If you must run a script:**

Create a script, e.g. `/home/YOUR_USERNAME/run_scan.py`:

```python
import urllib.request
import os
url = "https://YOUR_USERNAME.pythonanywhere.com/cron/scan?secret=" + os.environ.get("CRON_SECRET", "")
urllib.request.urlopen(url, timeout=120)
```

Then schedule:  
`/home/YOUR_USERNAME/venv/bin/python /home/YOUR_USERNAME/run_scan.py`  
(or use your project venv and ensure `CRON_SECRET` is set in the environment for that task).

---

## 7. Whitelist Telegram (free accounts)

On the free tier, PythonAnywhere only allows outbound HTTPS to whitelisted domains.

1. Open the **Account** (or **Network**) tab.
2. Add to the whitelist:  
   `api.telegram.org`  
   (and, if you use Yahoo/data APIs, any domains your code calls).

---

## 8. Test the bot

- In Telegram, send `/start` or `/status` to your bot.  
  Replies mean the webhook is working.
- Wait at least one minute and check that scan/trailing run (e.g. you get alerts when conditions are met, or check logs).

---

## Summary

| Step | What |
|------|------|
| 1 | PythonAnywhere account, note username |
| 2 | Clone repo, venv, `pip install -r requirements.txt` |
| 3 | Set `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CRON_SECRET` in env |
| 4 | Web app → Flask → WSGI loads `webhook_app.app`, reload |
| 5 | Set webhook: `https://USER.pythonanywhere.com/webhook` |
| 6 | Scheduled Task every minute → `/cron/scan?secret=CRON_SECRET` |
| 7 | Whitelist `api.telegram.org` (and other APIs if needed) |
| 8 | Test with `/start` and `/status` |

---

## Troubleshooting

- **No reply in Telegram**  
  - Check that the webhook is set:  
    `https://api.telegram.org/botYOUR_TOKEN/getWebhookInfo`  
  - Check the **Web** app **Error log** and **Server log** for 5xx or Python errors.

- **Scan/trailing not running**  
  - Confirm the scheduled task runs every minute and hits `/cron/scan?secret=...`.  
  - Check that `CRON_SECRET` matches.  
  - Check **Error log** for the web app when the cron URL is called.

- **“Something went wrong” in the browser**  
  - Check the WSGI file path and that `webhook_app` is importable (correct project path and venv).  
  - Reload the web app after any change.

- **Import or module errors**  
  - Ensure the **working directory** and **virtualenv** for the Web app point to `mnq_bot` and its `venv`.  
  - In the WSGI file, `sys.path.insert(0, path)` must point to the folder that contains `config.py`, `main.py`, `webhook_app.py`, and the `bot` package.
