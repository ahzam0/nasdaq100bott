# Deploy MNQ Bot Easily Online (PythonAnywhere)

Easiest way to run the bot 24/7 and get live Telegram signals: **PythonAnywhere** (free tier).

---

## In 5 steps

### 1. Sign up
- Go to [pythonanywhere.com](https://www.pythonanywhere.com) and create a free account.
- Note your **username** (e.g. `ahazm3333`). Your site will be:  
  `https://YOUR_USERNAME.pythonanywhere.com`

### 2. Clone and install
In the **Bash** console:

```bash
git clone https://github.com/ahzam0/nasdaq100bott.git
cd nasdaq100bott/mnq_bot
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Create the Web app
1. Open the **Web** tab → **Add a new web app** → **Flask** → **Python 3.10**.
2. Set **Source code** / project directory to: `/home/YOUR_USERNAME/nasdaq100bott/mnq_bot`
3. Open the **WSGI configuration file** and replace its content with:

```python
import sys
sys.path.insert(0, '/home/YOUR_USERNAME/nasdaq100bott/mnq_bot')
from run_bot_pa import application
```

(Replace `YOUR_USERNAME` with your actual username.)

4. Set **Virtualenv** to: `/home/YOUR_USERNAME/nasdaq100bott/mnq_bot/venv`
5. Click the green **Reload** button.  
   The bot is now running. Visiting `https://YOUR_USERNAME.pythonanywhere.com` should show: *"MNQ Bot is running."*

### 4. Set the Telegram webhook
Run **once** in the Bash console (or from your PC):

```bash
curl -F "url=https://YOUR_USERNAME.pythonanywhere.com/webhook" \
  "https://api.telegram.org/bot8510793606:AAE553KsIe0E6rAskRN-fUqM0H57_UN92zY/setWebhook"
```

Replace `YOUR_USERNAME` if different. After this, Telegram sends all updates to your app.

### 5. Run the scan every minute
1. In the **Tasks** (or **Schedule**) tab, add a **new task**.
2. If you have **“Run a URL”**:
   - **URL:** `https://YOUR_USERNAME.pythonanywhere.com/cron/scan?secret=mnqbotcron123`
   - **Schedule:** Every minute.
3. Save.

**Optional:** In **Account** → **Environment variables**, set `CRON_SECRET` to `mnqbotcron123` (or any secret) and use that same value in the URL above.  
The single-file app (`run_bot_pa.py`) already has token and chat ID fallbacks, so the bot can run without setting env vars.

---

## Whitelist (free accounts)
In **Account** (or **Network**) → **Whitelist**, add:
- `api.telegram.org`
- `query1.finance.yahoo.com` (for live data)

---

## Test
- In Telegram, send **/start** or **/status** to your bot. You should get a reply.
- During **7:00–11:00 AM EST**, the bot will scan and send live trade alerts when setups appear.

---

## Summary

| Step | Action |
|------|--------|
| 1 | Sign up at PythonAnywhere |
| 2 | Clone repo, venv, `pip install -r requirements.txt` |
| 3 | Web app → Flask → WSGI: `from run_bot_pa import application` → Reload |
| 4 | Set webhook with `curl` (see above) |
| 5 | Add scheduled task: hit `/cron/scan?secret=mnqbotcron123` every minute |
| + | Whitelist `api.telegram.org` and Yahoo if needed |

After this, the bot is deployed online and will send live signals in the 7–11 AM EST window.
