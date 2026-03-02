# Run full Yahoo WebSocket test suite
# Usage: .\run_yahoo_ws_tests.ps1   or   pwsh -File run_yahoo_ws_tests.ps1
Set-Location $PSScriptRoot
python -m unittest tests.test_yahoo_ws -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
