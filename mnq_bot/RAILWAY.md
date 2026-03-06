# Deploy MNQ Bot on Railway – Step-by-step

Railway gives you a public URL and runs your bot 24/7. Free tier has a monthly limit.

---

## 1. Sign up and create a project

1. Go to **[railway.app](https://railway.app)** and sign up (GitHub login is easiest).
2. Click **"New Project"**.
3. Choose **"Deploy from GitHub repo"**.
4. Select **ahzam0/nasdaq100bott** (or your fork). Authorize Railway if asked.

---

## 2. Set the root directory

The app code is in the **mnq_bot** folder, not the repo root.

1. Click your new **service** (the box that appeared).
2. Open the **Settings** tab.
3. Under **Build** or **Source**, find **"Root Directory"** or **"Watch Paths"**.
4. Set **Root Directory** to:
   ```
   mnq_bot
   ```
5. Save.

*(If you don't see Root Directory, check under "Source" or in the service "Settings". Some UIs use "Monorepo" or "Subdirectory" = `mnq_bot`.)*

---

## 3. Add environment variables (optional)

Your bot has token/chat ID in code, so it can run without these. To override or hide them:

1. In the service, go to the **Variables** tab.
2. Add (if you want to override):

   | Name | Value |
   |------|--------|
   | `TELEGRAM_BOT_TOKEN` | Your bot token |
   | `TELEGRAM_CHAT_ID` | Your chat ID (e.g. 8309667442) |
   | `CRON_SECRET` | e.g. mnqbotcron123 |
   | `APP_BASE_URL` | (optional) Your app URL for auto webhook, e.g. `https://nasdaq100bott-production.up.railway.app` |
   | `MNQ_DATA_DIR` | (optional) Persistent data path, e.g. `/data` – set this when using a Volume so trade history & balance survive restarts |

---

## 4. Deploy

1. Railway usually **auto-deploys** when you connect the repo. If not, click **"Deploy"** or **"Redeploy"**.
2. Wait until the build finishes (Build → Run).
3. Open the **Settings** tab and find **"Networking"** or **"Domains"**.
4. Click **"Generate Domain"** (or **"Add domain"**). You'll get a URL like:
   ```
   https://nasdaq100bott-production-xxxx.up.railway.app
   ```
5. Copy this URL; you'll use it as **YOUR_RAILWAY_URL** below.

---

## 5. Set the Telegram webhook

**Auto on startup:** The app automatically sets the Telegram webhook when it starts (and again after any crash restart). Railway sets `RAILWAY_PUBLIC_DOMAIN`; if your URL is different, set **Variables** → `APP_BASE_URL` = `https://nasdaq100bott-production.up.railway.app` (your real app URL). No manual step needed after the first deploy.

**Manual (if needed):** Open in browser:
```
https://YOUR_RAILWAY_URL/set-webhook?secret=mnqbotcron123
```
Example: [https://nasdaq100bott-production.up.railway.app/set-webhook?secret=mnqbotcron123](https://nasdaq100bott-production.up.railway.app/set-webhook?secret=mnqbotcron123)

The page will show "Webhook set to https://...".

---

## 6. (Recommended) Keep trade history and balance across restarts

By default, the app saves trade history and P&L to `data/trade_data.json`. On Railway the disk is **ephemeral**, so a redeploy or restart can wipe that file and you lose history/balance.

To **persist** it:

1. In your Railway service, open **Settings** → **Volumes** (or **Storage**).
2. Click **Add Volume**, set mount path to **`/data`** (or e.g. `/app/data` if your app runs from `/app`).
3. In **Variables**, add:
   - **`MNQ_DATA_DIR`** = **`/data`** (must match the volume mount path exactly).
4. Redeploy. The bot will write `trade_data.json` and `bot_state.json` under `/data`, so they survive restarts.

After this, when you restart or redeploy, the bot will load previous trade history and balance from the volume.

## 7. Crash restart and scan

- **Crash:** Railway restarts the process automatically if the app crashes. On restart, the webhook is set again so the bot keeps working.
- **Scan:** The app runs the scan every 60 seconds inside the process. No external cron needed.

---

## 8. Test the bot

1. In Telegram, send **/start** or **/status** to your bot. You should get a reply.
2. Visit **https://YOUR_RAILWAY_URL/** in a browser. You should see:  
   `MNQ Bot is running. /webhook for Telegram, /cron/scan for scan.`

---

## Summary

| Step | What you did |
|------|------------------|
| 1 | Signed up at Railway, new project from GitHub **ahzam0/nasdaq100bott** |
| 2 | Set **Root Directory** to **mnq_bot** |
| 3 | (Optional) Added TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CRON_SECRET |
| 4 | Deployed and copied your **Railway URL** |
| 5 | Opened **YOUR_RAILWAY_URL/set-webhook?secret=mnqbotcron123** in browser (webhook set automatically) |
| 6 | (Optional) Added Volume + MNQ_DATA_DIR so trade history & balance survive restarts |
| 7 | No cron needed – app runs scan every 60 sec inside the process |
| 8 | Tested with /start and the root URL |

After this, the bot runs on Railway and sends live signals during **7–11 AM EST**.

---

## Troubleshooting

- **Build fails:** Ensure Root Directory is exactly `mnq_bot` and that `requirements.txt` and `Procfile` are in that folder.
- **502 / App not starting:** Check the **Deploy** or **Logs** tab for errors. Ensure `gunicorn run_bot_pa:application` runs (Procfile).
- **Bot not responding to buttons / commands:**  
  1. **Set the webhook** – After every deploy, open in a browser:  
     `https://YOUR_RAILWAY_URL/set-webhook?secret=YOUR_CRON_SECRET`  
     (e.g. `.../set-webhook?secret=mnqbotcron123`). You must do this once so Telegram sends updates to your app.  
  2. **Confirm webhook** – Open:  
     `https://api.telegram.org/botYOUR_BOT_TOKEN/getWebhookInfo`  
     It should show `"url": "https://YOUR_RAILWAY_URL/webhook"`.  
  3. The Procfile uses **2 workers** so /webhook can be served while the scan runs; if you overrode the start command, keep at least 2 workers.
- **No reply in Telegram:** Same as above: confirm webhook is set to your app URL (getWebhookInfo).
- **Scans not running:** The app runs the scan every 60 seconds; check Railway logs for errors when the scheduler runs.
