# Run 3-month live backtest (current strategy – Yahoo NQ=F, 7–11 EST)
Set-Location $PSScriptRoot
$risk = 380   # Original preset: ~35% return, 54 trades, 3.06% DD (see BACKTEST_3M_RESULT.md)
$args = @('run_backtest.py', '--live', '--months', '3', '--balance', '50000', '--risk', $risk)
if (Get-Command python -ErrorAction SilentlyContinue) { python @args }
elseif (Get-Command py -ErrorAction SilentlyContinue) { py -3 @args }
else { Write-Error "Python not found. Add Python to PATH or run: python run_backtest.py --live --months 3 --balance 50000 --risk $risk" }
Read-Host 'Press Enter to close'
