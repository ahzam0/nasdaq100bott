# Run backtest on previous 1 month of live data (Yahoo 15m -> 1m, 7-11 EST)
Set-Location $PSScriptRoot
$args = @('run_backtest.py', '--live', '--months', '1', '--balance', '50000', '--risk', '330')
if (Get-Command python -ErrorAction SilentlyContinue) { python @args }
elseif (Get-Command py -ErrorAction SilentlyContinue) { py @args }
else { Write-Error 'Python not found. Add Python to PATH or run: python run_backtest.py --live --months 1' }
Read-Host 'Press Enter to close'
