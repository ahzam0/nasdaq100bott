@echo off
cd /d "%~dp0"
REM Primary: 3 months, 7-11 EST, $50k, $380/trade
python run_backtest.py --live --months 3 --balance 50000 --risk 380
if errorlevel 1 (
  py -3 run_backtest.py --live --months 3 --balance 50000 --risk 380
)
pause
