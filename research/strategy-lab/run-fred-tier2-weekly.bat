@echo off
REM Weekly refresh: FRED tier-2 series (monthly/quarterly economic releases).
REM Created by Claude, wired into Windows Task Scheduler task "StockUI-FRED-Tier2-Weekly".
REM 2026-09-26: build_ui_macro.py removed - GitHub Actions macro-regime-ui builds and commits ui/data/macro.json daily;
REM rebuilding it here made the PC copy diverge every morning and blocked git pull. This task now only refreshes local FRED data.
cd /d "%~dp0"
"C:\Users\User\AppData\Local\Programs\Python\Python313\python.exe" build_fred_extended_backfill.py --tier 2 >> fred_tier2_weekly.log 2>&1
