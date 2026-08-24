@echo off
REM Daily refresh: FRED tier-1 series (daily/weekly market data) + UI macro feed rebuild.
REM Created by Claude, wired into Windows Task Scheduler task "StockUI-FRED-Tier1-Daily".
cd /d "%~dp0"
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" build_fred_extended_backfill.py --tier 1 >> fred_tier1_daily.log 2>&1
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" build_ui_macro.py >> fred_tier1_daily.log 2>&1
