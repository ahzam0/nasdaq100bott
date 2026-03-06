"""
Plotly Dash NASDAQ dashboard: KPIs, equity curve, drawdown, sector exposure,
trade log, positions, quantum convergence, risk panel.
"""

from __future__ import annotations

import json
from pathlib import Path

import dash
from dash import dcc, html
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent.parent
LAYOUT = [
    html.H1("NASDAQ Quantum Trading Dashboard", style={"textAlign": "center"}),
    html.Div([
        html.Div([html.H4("Today P&L"), html.Div(id="kpi-pnl", children="$0")], className="kpi"),
        html.Div([html.H4("Portfolio Value"), html.Div(id="kpi-portfolio", children="$0")], className="kpi"),
        html.Div([html.H4("Open Positions"), html.Div(id="kpi-positions", children="0")], className="kpi"),
        html.Div([html.H4("Targets Hit"), html.Div(id="kpi-targets", children="0/10")], className="kpi"),
    ], style={"display": "flex", "gap": "20px", "marginBottom": "20px"}),
    html.Div([
        dcc.Graph(id="chart-equity", figure=go.Figure().add_trace(go.Scatter(x=[], y=[], name="Equity"))),
        dcc.Graph(id="chart-drawdown", figure=go.Figure().add_trace(go.Scatter(x=[], y=[], name="Drawdown %"))),
    ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr"}),
    html.Div([
        html.H4("Trade log"),
        html.Pre(id="trade-log", children="No trades yet."),
    ]),
    html.Div([
        html.H4("Risk monitor"),
        html.Div(id="risk-status", children="Beta: — | VIX: — | Circuit: —"),
    ]),
    dcc.Interval(id="interval", interval=60_000),
]


def create_app() -> dash.Dash:
    app = dash.Dash(__name__, title="NASDAQ Quantum Bot")
    app.layout = html.Div(LAYOUT, style={"fontFamily": "sans-serif", "padding": "20px"})
    return app


app = create_app()


@app.callback(
    [dash.Output("kpi-pnl", "children"), dash.Output("kpi-portfolio", "children"), dash.Output("kpi-targets", "children")],
    dash.Input("interval", "n_intervals"),
)
def update_kpis(n):
    try:
        lb = ROOT / "output" / "leaderboard.json"
        if lb.exists():
            with open(lb) as f:
                data = json.load(f)
            if data:
                best = data[0]
                return f"Score {best.get('score', 0):.2f}", "—", "—"
    except Exception:
        pass
    return "$0", "$0", "0/10"


if __name__ == "__main__":
    app.run_server(debug=True, port=8050)
