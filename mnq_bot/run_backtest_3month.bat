@echo off
cd /d "%~dp0"
REM 3-month live backtest, risk 380 (original preset: ~35% / 54 trades)
python run_backtest.py --live --months 3 --balance 50000 --risk 380
if errorlevel 1 py -3 run_backtest.py --live --months 3 --balance 50000 --risk 380
pause
