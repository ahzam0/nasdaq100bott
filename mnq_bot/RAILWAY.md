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

*(If you don’t see Root Directory, check under "Source" or in the service "Settings". Some UIs use "Monorepo" or "Subdirectory" = `mnq_bot`.)*

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

---

## 4. Deploy

1. Railway usually **auto-deploys** when you connect the repo. If not, click **"Deploy"** or **"Redeploy"**.
2. Wait until the build finishes (Build → Run).
3. Open the **Settings** tab and find **"Networking"** or **"Domains"**.
4. Click **"Generate Domain"** (or **"Add domain"**). You’ll get a URL like:
   ```
   https://nasdaq100bott-production-xxxx.up.railway.app
   ```
5. Copy this URL; you’ll use it as **YOUR_RAILWAY_URL** below.

---

## 5. Set the Telegram webhook

Replace **YOUR_RAILWAY_URL** with your real URL (e.g. `https://nasdaq100bott-production-xxxx.up.railway.app`).

**On Windows (PowerShell):**
```powershell
$url = "YOUR_RAILWAY_URL"
curl.exe -F "url=$url/webhook" "https://api.telegram.org/bot8510793606:AAE553KsIe0E6rAskRN-fUqM0H57_UN92zY/setWebhook"
```

**On Mac/Linux or Bash:**
```bash
curl -F "url=YOUR_RAILWAY_URL/webhook" "https://api.telegram.org/bot8510793606:AAE553KsIe0E6rAskRN-fUqM0H57_UN92zY/setWebhook"
```

Example if your URL is `https://mnqbot.up.railway.app`:
```bash
curl -F "url=https://mnqbot.up.railway.app/webhook" "https://api.telegram.org/bot8510793606:AAE553KsIe0E6rAskRN-fUqM0H57_UN92zY/setWebhook"
```

---

## 6. Run the scan every minute (cron)

Railway doesn’t have a built-in cron. Use a free external cron:

1. Go to **[cron-job.org](https://cron-job.org)** (or similar) and create a free account.
2. Create a new **Cron Job**:
   - **URL:**  
     `https://YOUR_RAILWAY_URL/cron/scan?secret=mnqbotcron123`
   - **Schedule:** Every minute (e.g. `* * * * *` or “Every minute”).
3. Save.

Replace **YOUR_RAILWAY_URL** with the same URL from step 4. If you set `CRON_SECRET` in Variables, use that value instead of `mnqbotcron123`.

---

## 7. Test the bot

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
| 5 | Set Telegram webhook to **YOUR_RAILWAY_URL/webhook** |
| 6 | Added cron-job.org to call **YOUR_RAILWAY_URL/cron/scan?secret=mnqbotcron123** every minute |
| 7 | Tested with /start and the root URL |

After this, the bot runs on Railway and sends live signals during **7–11 AM EST**.

---

## Troubleshooting

- **Build fails:** Ensure Root Directory is exactly `mnq_bot` and that `requirements.txt` and `Procfile` are in that folder.
- **502 / App not starting:** Check the **Deploy** or **Logs** tab for errors. Ensure `gunicorn run_bot_pa:application` runs (Procfile).
- **No reply in Telegram:** Confirm webhook:  
  `https://api.telegram.org/bot8510793606:AAE553KsIe0E6rAskRN-fUqM0H57_UN92zY/getWebhookInfo`  
  It should show your Railway URL.
- **Scans not running:** Confirm the cron job URL is correct and the cron runs every minute; check Railway logs when the URL is hit.
