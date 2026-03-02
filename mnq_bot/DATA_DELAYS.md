# Data Fetching & Delay Audit

This document describes **every data source** the app uses, whether it has **delay**, and how to get **minimal or zero delay** where possible.

---

## Summary

| Data | Used for | Default source | Delay? | Zero/minimal-delay option |
|------|----------|-----------------|--------|----------------------------|
| **1m candles** | Setups, key levels | Yahoo (yfinance) | **Yes** (Yahoo free is delayed) | Tradovate/broker history or run Price API with real-time backend |
| **15m candles** | Structure, trend, levels | Yahoo (yfinance) | **Yes** (same) | Same as 1m |
| **Current price** | Trailing, alerts | Yahoo REST or Yahoo WS | **REST: Yes; WS: Minimal** | Yahoo WS (default) or Tradovate realtime |
| **Order flow** | Entry confirmation | Your API (GET /orderflow/summary) | **No** if you feed via POST | Feed from broker/SC; 2s timeout per scan |
| **Economic calendar** | News buffer | Forex Factory HTTP (or manual times) | Cached 60 min; parser + manual override | Use CALENDAR_MANUAL_HIGH_IMPACT_TIMES if FF blocks |

**Conclusion:** **Not all data is delay-free by default.** Current price can be minimal-delay (Yahoo WS) or delay-free (Tradovate). **Candles are delayed** on free Yahoo; for **real-time 1m/15m candles** use a broker or paid feed and plug it into the Price API backend or `data/feed.py` (Tradovate/NinjaTrader can provide delay-free candles when implemented).

---

## 1. Price & candlestick data

### Feed selection order (in `data/feed.py` → `get_feed()`)

1. **Tradovate realtime** (if `BROKER=tradovate`, `TRADOVATE_USE_REALTIME_MD=True`, credentials set)  
   - **Current price:** delay-free (WebSocket).  
   - **1m/15m candles:** still from **Yahoo** in code → **delayed**.

2. **Yahoo WebSocket** (if `USE_YAHOO_WS_REALTIME=True`, default)  
   - **Current price:** minimal delay (QQQ stream → NQ equivalent).  
   - **1m/15m candles:** from **Yahoo REST** → **delayed** (Yahoo free tier).

3. **Local Price API** (if `PRICE_API_URL` set, e.g. `http://127.0.0.1:5001`)  
   - **Current price:** cache TTL 5s; backend = Yahoo WS or Tradovate if configured in API, else Yahoo REST → **delayed** unless API uses WS/Tradovate.  
   - **1m/15m:** cache TTL 30s; backend Yahoo REST → **delayed**.

4. **Yahoo REST only** (`YahooFinanceFeed`)  
   - **Current price** and **candles:** Yahoo Finance (NQ=F) → **delayed** (typical free-tier delay).

So:

- **Current price** can be **minimal or no delay** with Yahoo WS (default) or Tradovate.
- **1m/15m candles** are **not** delay-free on default/free setup; they always come from Yahoo REST in the current code paths (including when Tradovate is used for price).

### Where it’s used

- **Scan:** `feed.get_1m_candles(100)`, `feed.get_15m_candles(50)` → setup detection, key levels.  
- **Trailing:** `feed.get_current_price()` → stop/trail checks.

### How to reduce delay

- **Current price:** Keep `USE_YAHOO_WS_REALTIME=True` or use Tradovate realtime.  
- **Candles:** Use a data provider that offers real-time 1m/15m (e.g. broker API, CME, or a paid feed) and plug it into the feed/Price API; no change to strategy logic required.

---

## 2. Order flow

- **Source:** `GET {ORDERFLOW_API_URL}/orderflow/summary` (timeout 2s).  
- **When:** Only when a setup is detected and `USE_ORDERFLOW=True`.  
- **Delay:** None from the app’s side if your order flow server is fed in real time (e.g. via `POST /orderflow/push` from your broker/SC).  
- **Latency:** Up to **2s** added to the scan when order flow is enabled (HTTP timeout). For zero delay, keep the order flow server local and fast.

---

## 3. Economic calendar

- **Source:** HTTP GET to Forex Factory (timeout 10s).  
- **When:** On every `validate_entry()` when a setup is found (i.e. not every tick, but every time a candidate trade is checked).  
- **Delay:**  
  - **Before fix:** One HTTP request per validation, up to 10s.  
  - **After fix:** Results are **cached for 60 minutes**; one request per hour max.  
- **Parser:** Placeholder only (`_parse_forexfactory` returns `[]`), so no events are used yet; the main cost was the repeated HTTP call, now reduced by caching.

---

## 4. Other

- **Telegram:** Outbound only; no data “fetch” delay.  
- **Config / state:** In-memory; no network delay.

---

## Is Yahoo WebSocket actually working?

The app uses **yfinance’s WebSocket** when `USE_YAHOO_WS_REALTIME=True` (default): it subscribes to **QQQ** and scales to an NQ-equivalent price.

- **When it works:** You get near real-time price (seconds delay). The feed logs: `Using Yahoo WebSocket feed (free, minimal delay)`.
- **When it doesn’t:** No price from WS within ~10s, or yfinance has no WebSocket / different message format. Then **current price** falls back to **Yahoo REST** (15–20 min delayed). Candles are always from Yahoo REST in the free path.

**Check on your machine:**

```bash
python scripts/check_yahoo_ws.py
```

If you see `OK – Yahoo WebSocket is working` and a QQQ/NQ price, WS is active. If you see “No price received”, the bot still runs but uses delayed REST for price. Upgrade yfinance if needed: `pip install --upgrade yfinance`.

---

## Recommendations

1. **Current price:** Use Yahoo WS (default) or Tradovate realtime; avoid relying on Yahoo REST for price only.  
2. **Candles:** Accept delayed 1m/15m on free tier, or integrate a real-time candle source (broker/Price API backend).  
3. **Order flow:** Keep server local and feed it in real time; 2s timeout is acceptable for scan-based flow.  
4. **Calendar:** Caching is implemented; when you implement the parser, keep the 60-minute cache to avoid repeated requests.
