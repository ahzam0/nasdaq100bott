# Run our Order Flow API. No API key = simulated order flow from free candle data.
# Optional: set POLYGON_API_KEY + MNQ_ORDERFLOW_FROM_POLYGON=true for real tick data.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

& python -m api.orderflow_server
