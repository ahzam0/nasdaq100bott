@echo off
cd /d "%~dp0"
REM Run optimizer then live backtest with best config
py -3 run_optimize_then_backtest.py %*
if errorlevel 1 python run_optimize_then_backtest.py %*
pause
