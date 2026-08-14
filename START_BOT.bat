@echo off
setlocal
cd /d "%~dp0"
echo ============================================
echo   KALSHI V11 PAPER-ONLY RESEARCH COLLECTOR
echo ============================================
echo.
echo This launcher does NOT place, amend, cancel, or sell Kalshi orders.
echo It records live public game and market observations for validation.
echo.
if not exist config.json (
  echo ERROR: config.json is required for authenticated read-only market data.
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
python research\daemon.py --config config.json --interval-seconds 60
pause
