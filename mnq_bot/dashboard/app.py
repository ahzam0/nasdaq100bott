"""
MNQ Trading Bot – Web Dashboard
Flask-based single-page dashboard with dark theme.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root on path when run as python -m dashboard.app
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Template: dark theme, stats cards, live price, trade table, equity chart
# ---------------------------------------------------------------------------
DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>MNQ Riley Coleman Bot – Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #1a1a2e;
      --card: #16213e;
      --card-border: #0f3460;
      --text: #e8e8e8;
      --text-muted: #a0a0a0;
      --profit: #00ff88;
      --loss: #ff4444;
      --info: #4488ff;
      --radius: 12px;
      --shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
      line-height: 1.5;
    }
    .container { max-width: 1200px; margin: 0 auto; padding: 1rem; }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 1rem;
      padding: 1rem 0;
      border-bottom: 1px solid var(--card-border);
    }
    .bot-title { font-size: 1.5rem; font-weight: 600; }
    .status-dot {
      width: 10px; height: 10px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 6px;
      animation: pulse 2s infinite;
    }
    .status-dot.active { background: var(--profit); }
    .status-dot.paused { background: var(--loss); }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
    .stats-row {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem;
      margin: 1.5rem 0;
    }
    .stat-card {
      background: var(--card);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 1.25rem;
      box-shadow: var(--shadow);
    }
    .stat-label { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 0.25rem; }
    .stat-value { font-size: 1.5rem; font-weight: 700; }
    .stat-value.profit { color: var(--profit); }
    .stat-value.loss { color: var(--loss); }
    .stat-value.neutral { color: var(--info); }
    .price-box {
      background: var(--card);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 1rem 1.5rem;
      margin-bottom: 1.5rem;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 1rem;
    }
    .price-label { color: var(--text-muted); }
    .price-value { font-size: 1.75rem; font-weight: 700; color: var(--info); }
    .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }
    @media (max-width: 768px) { .grid-2 { grid-template-columns: 1fr; } }
    .panel {
      background: var(--card);
      border: 1px solid var(--card-border);
      border-radius: var(--radius);
      padding: 1.25rem;
      box-shadow: var(--shadow);
    }
    .panel h2 { font-size: 1.1rem; margin-bottom: 1rem; color: var(--text-muted); }
    .trades-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.9rem;
    }
    .trades-table th, .trades-table td { padding: 0.5rem 0.75rem; text-align: left; }
    .trades-table th { color: var(--text-muted); font-weight: 500; }
    .trades-table tr:nth-child(even) { background: rgba(255,255,255,0.03); }
    .trades-scroll { max-height: 280px; overflow-y: auto; }
    .config-list { list-style: none; }
    .config-list li { padding: 0.4rem 0; border-bottom: 1px solid rgba(255,255,255,0.06); display: flex; justify-content: space-between; }
    .config-list li:last-child { border-bottom: none; }
    .config-key { color: var(--text-muted); }
    .config-val { font-weight: 500; }
    .chart-container { position: relative; height: 280px; }
    .empty-msg { color: var(--text-muted); font-style: italic; padding: 1rem; }
    .refresh-info { font-size: 0.8rem; color: var(--text-muted); margin-top: 1rem; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <span class="bot-title">MNQ Riley Coleman Bot</span>
        <span id="status-dot" class="status-dot"></span>
        <span id="status-text">—</span>
      </div>
      <div class="refresh-info">Auto-refresh: 30s &nbsp;|&nbsp; Price: 10s</div>
    </header>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-label">Daily P&L</div>
        <div id="stat-pnl" class="stat-value">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Win Rate</div>
        <div id="stat-wr" class="stat-value">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Total Trades</div>
        <div id="stat-trades" class="stat-value">—</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Active Trades</div>
        <div id="stat-active" class="stat-value">—</div>
      </div>
    </div>

    <div class="price-box">
      <span class="price-label">Live MNQ Price</span>
      <span id="live-price" class="price-value">—</span>
    </div>

    <div class="grid-2">
      <div class="panel">
        <h2>Equity Curve</h2>
        <div class="chart-container">
          <canvas id="equity-chart"></canvas>
        </div>
      </div>
      <div class="panel">
        <h2>Trade History (Last 20)</h2>
        <div class="trades-scroll">
          <table class="trades-table">
            <thead><tr><th>Dir</th><th>Entry</th><th>Result</th><th>P&L</th></tr></thead>
            <tbody id="trades-body"></tbody>
          </table>
          <div id="trades-empty" class="empty-msg" style="display:none;">No trades yet.</div>
        </div>
      </div>
    </div>

    <div class="panel" style="margin-top: 1.5rem;">
      <h2>Strategy Config</h2>
      <ul class="config-list" id="config-list"></ul>
    </div>
  </div>

  <script>
    let equityChart = null;

    function fmtPnl(v) {
      if (v == null) return '—';
      const n = Number(v);
      const s = n >= 0 ? '+' + n.toFixed(0) : n.toFixed(0);
      return '$' + s;
    }

    function setPnlClass(el, val) {
      el.classList.remove('profit','loss','neutral');
      if (val == null) return;
      const n = Number(val);
      el.classList.add(n > 0 ? 'profit' : n < 0 ? 'loss' : 'neutral');
    }

    async function fetchJson(path) {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 15000);
      try {
        const r = await fetch(path, { signal: ctrl.signal });
        clearTimeout(t);
        if (!r.ok) throw new Error(r.statusText);
        return r.json();
      } catch (e) {
        clearTimeout(t);
        if (e.name === 'AbortError') throw new Error('Request timeout');
        throw e;
      }
    }

    async function refreshStatus() {
      try {
        const d = await fetchJson('/api/status');
        document.getElementById('status-dot').className = 'status-dot ' + (d.scan_active ? 'active' : 'paused');
        document.getElementById('status-text').textContent = d.scan_active ? 'Scanning' : 'Paused';
        document.getElementById('stat-pnl').textContent = fmtPnl(d.daily_pnl);
        setPnlClass(document.getElementById('stat-pnl'), d.daily_pnl);
        document.getElementById('stat-wr').textContent = d.win_rate != null ? d.win_rate.toFixed(1) + '%' : '—';
        document.getElementById('stat-trades').textContent = d.total_trades != null ? String(d.total_trades) : '—';
        document.getElementById('stat-active').textContent = d.active_trades != null ? String(d.active_trades) : '—';
      } catch (e) {
        document.getElementById('status-text').textContent = 'Error';
      }
    }

    async function refreshPrice() {
      try {
        const d = await fetchJson('/api/price');
        const el = document.getElementById('live-price');
        if (d.price != null) el.textContent = Number(d.price).toLocaleString('en-US', {minimumFractionDigits: 2});
        else el.textContent = '—';
      } catch (e) {
        document.getElementById('live-price').textContent = '—';
      }
    }

    async function refreshEquity() {
      try {
        const d = await fetchJson('/api/equity');
        const labels = (d.labels || []);
        const data = (d.data || []);
        const ctx = document.getElementById('equity-chart').getContext('2d');
        if (equityChart) equityChart.destroy();
        if (labels.length === 0) {
          equityChart = null;
          return;
        }
        equityChart = new Chart(ctx, {
          type: 'line',
          data: {
            labels: labels,
            datasets: [{
              label: 'Equity',
              data: data,
              borderColor: '#4488ff',
              backgroundColor: 'rgba(68,136,255,0.1)',
              fill: true,
              tension: 0.2
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { color: '#a0a0a0', maxTicksLimit: 8 } },
              y: { ticks: { color: '#a0a0a0' } }
            }
          }
        });
      } catch (e) {
        if (equityChart) { equityChart.destroy(); equityChart = null; }
      }
    }

    async function refreshTrades() {
      try {
        const d = await fetchJson('/api/trades');
        const rows = d.trades || [];
        const tbody = document.getElementById('trades-body');
        const empty = document.getElementById('trades-empty');
        tbody.innerHTML = '';
        if (rows.length === 0) {
          empty.style.display = 'block';
          return;
        }
        empty.style.display = 'none';
        rows.slice(0, 20).forEach(t => {
          const tr = document.createElement('tr');
          const pnl = t.pnl != null ? t.pnl : 0;
          const pnlClass = pnl > 0 ? 'profit' : pnl < 0 ? 'loss' : '';
          tr.innerHTML = '<td>' + (t.dir || '—') + '</td><td>' + (t.entry != null ? Number(t.entry).toFixed(2) : '—') + '</td><td>' + (t.result || '—') + '</td><td class="' + pnlClass + '">' + fmtPnl(pnl) + '</td>';
          tbody.appendChild(tr);
        });
      } catch (e) {
        document.getElementById('trades-empty').textContent = 'Could not load trades.';
        document.getElementById('trades-empty').style.display = 'block';
      }
    }

    async function refreshConfig() {
      try {
        const d = await fetchJson('/api/config');
        const list = document.getElementById('config-list');
        list.innerHTML = '';
        const items = d.config || [];
        items.forEach(([k, v]) => {
          const li = document.createElement('li');
          li.innerHTML = '<span class="config-key">' + k + '</span><span class="config-val">' + v + '</span>';
          list.appendChild(li);
        });
      } catch (e) {}
    }

    function refreshAll() {
      refreshStatus();
      refreshTrades();
      refreshEquity();
      refreshConfig();
    }

    refreshAll();
    refreshPrice();
    setInterval(refreshPrice, 10000);
    setInterval(refreshAll, 30000);
  </script>
</body>
</html>
"""


def _get_feed():
    """Get data feed for live price. Lazy import to avoid circular deps."""
    from config import BROKER, USE_LIVE_FEED, PRICE_API_URL
    from data import get_feed
    return get_feed(BROKER, use_live_feed=USE_LIVE_FEED, price_api_url=PRICE_API_URL)


def _get_equity_data():
    """Read equity curve from data/equity_curve.json or equity_tracker."""
    try:
        from data.equity_tracker import get_equity_curve
        snapshots = get_equity_curve()
    except Exception:
        curve_path = ROOT / "data" / "equity_curve.json"
        if curve_path.exists():
            data = json.loads(curve_path.read_text(encoding="utf-8"))
            snapshots = data if isinstance(data, list) else data.get("snapshots", [])
        else:
            snapshots = []
    labels = []
    values = []
    for s in snapshots:
        ts = s.get("timestamp", "")
        labels.append(ts[:10] if len(ts) >= 10 else ts)
        values.append(float(s.get("balance", 0)))
    return {"labels": labels, "data": values}


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/status")
def api_status():
    try:
        from bot.commands import get_state
        from config import MAX_TRADES_PER_DAY
        state = get_state()
        history = state.get("trade_history", [])
        winners = sum(1 for h in history if (h.get("pnl") or 0) > 0)
        total = len(history)
        wr = (100 * winners / total) if total else 0
        return jsonify({
            "scan_active": state.get("scan_active", True),
            "trades_today": state.get("trades_today", 0),
            "daily_pnl": state.get("daily_pnl", 0),
            "active_trades": len(state.get("active_trades", [])),
            "total_trades": total,
            "win_rate": round(wr, 1),
            "max_trades_per_day": MAX_TRADES_PER_DAY,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/equity")
def api_equity():
    try:
        return jsonify(_get_equity_data())
    except Exception as e:
        return jsonify({"labels": [], "data": [], "error": str(e)})


@app.route("/api/trades")
def api_trades():
    try:
        from bot.commands import get_state
        state = get_state()
        history = state.get("trade_history", [])[-50:]
        trades = [
            {
                "dir": h.get("dir"),
                "entry": h.get("entry"),
                "result": h.get("result"),
                "pnl": h.get("pnl"),
                "date": h.get("date"),
            }
            for h in reversed(history)
        ]
        return jsonify({"trades": trades})
    except Exception as e:
        return jsonify({"trades": [], "error": str(e)})


@app.route("/api/price")
def api_price():
    try:
        feed = _get_feed()
        price = feed.get_current_price() if feed.is_connected() else None
        return jsonify({"price": price})
    except Exception as e:
        return jsonify({"price": None, "error": str(e)})


@app.route("/api/config")
def api_config():
    try:
        from config import (
            INSTRUMENT,
            MAX_RISK_PER_TRADE_USD,
            MAX_TRADES_PER_DAY,
            MIN_RR_RATIO,
            MAX_RISK_PTS,
            LEVEL_TOLERANCE_PTS,
            RETEST_ONLY,
            REQUIRE_TREND_ONLY,
            TP1_RR,
            TP2_RR,
            SCAN_SESSION_EST,
        )
        from bot.commands import get_state
        state = get_state()
        items = [
            ("Instrument", INSTRUMENT),
            ("Risk/trade", f"${state.get('risk_per_trade', MAX_RISK_PER_TRADE_USD):.0f}"),
            ("Contracts", str(state.get("contracts", 1))),
            ("Max trades/day", str(MAX_TRADES_PER_DAY)),
            ("Min R:R", str(MIN_RR_RATIO)),
            ("TP1 R:R", str(TP1_RR)),
            ("TP2 R:R", str(TP2_RR)),
            ("Max risk pts", str(MAX_RISK_PTS)),
            ("Level tolerance", str(LEVEL_TOLERANCE_PTS)),
            ("Retest only", str(RETEST_ONLY)),
            ("Require trend", str(REQUIRE_TREND_ONLY)),
            ("Session", SCAN_SESSION_EST),
        ]
        return jsonify({"config": items})
    except Exception as e:
        return jsonify({"config": [], "error": str(e)})


def start_dashboard(host: str = "0.0.0.0", port: int = 5050, debug: bool = False) -> None:
    """Start the Flask dashboard server. Threaded so requests stay responsive while bot runs."""
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == "__main__":
    start_dashboard(host="0.0.0.0", port=5050, debug=False)
