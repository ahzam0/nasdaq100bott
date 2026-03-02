@echo off
cd /d "%~dp0"
python run_backtest.py --live --months 1 --balance 50000 --risk 330
if errorlevel 1 py run_backtest.py --live --months 1 --balance 50000 --risk 330
pause
