# Order Flow – No API Key

Order flow works **without any API key**. Just run the order flow server; it uses the **same free price/candle data** the bot already uses (Yahoo, etc.).

## No API key (default)

1. Start the order flow server:
   ```powershell
   python -m api.orderflow_server
   ```
2. It automatically starts the **simulated** order flow feed: delta is inferred from the last 1m candle (close vs open, volume). Same free data source as the bot — **no Polygon, no Tradovate, no key**.
3. Point the bot at it: `MNQ_ORDERFLOW_API_URL=http://127.0.0.1:5002` (default). Turn order flow ON in Telegram.

So you get order flow (candle-based proxy) with **zero API keys**.

## What “simulated” means

- **Source:** Last 1m candle from your price feed (Yahoo by default).
- **Logic:** Close > open → buy pressure; close < open → sell pressure; volume used for size.
- **Delay:** Same as 1m candles (not tick-level). Good enough for strategy confirmation; not real-time tape.

## Optional: real tick-level order flow (with API key)

If you later add a key (e.g. Polygon), you can switch to real trades:

- Set `POLYGON_API_KEY` and `MNQ_ORDERFLOW_FROM_POLYGON=true` — then the server uses Polygon’s trade stream instead of the simulated feed.

Until then, **no API key** = simulated order flow from free data only.
