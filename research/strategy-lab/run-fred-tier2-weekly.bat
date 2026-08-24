@echo off
REM Weekly refresh: FRED tier-2 series (monthly/quarterly economic releases) + UI macro feed rebuild.
REM Created by Claude, wired into Windows Task Scheduler task "StockUI-FRED-Tier2-Weekly".
cd /d "%~dp0"
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" build_fred_extended_backfill.py --tier 2 >> fred_tier2_weekly.log 2>&1
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" build_ui_macro.py >> fred_tier2_weekly.log 2>&1
