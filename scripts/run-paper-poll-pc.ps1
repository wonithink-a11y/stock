# Runs the strategy paper-trading poll (run_paper_trading_daily.py) once on this PC. Called by Task Scheduler
# (see register-paper-poll-task.ps1). ASCII only on purpose: Windows PowerShell 5.1 reads BOM-less files as ANSI
# and a Korean comment can swallow the newline after it.
#   default = dry-run (no orders reach KIS). -Live sends real orders to the KIS paper (VTS) account.
#   Reads KIS paper keys from .env into this process only. Log: autotrader\state\pc-paper-poll.log (gitignored).
# Usage:
#   powershell -File scripts\run-paper-poll-pc.ps1          # dry-run
#   powershell -File scripts\run-paper-poll-pc.ps1 -Live    # paper orders
param([switch]$Live)
$repo = Split-Path $PSScriptRoot -Parent
Set-Location (Join-Path $repo 'research\strategy-lab')
$env:PYTHONIOENCODING = 'utf-8'
$log = Join-Path $repo 'autotrader\state\pc-paper-poll.log'
Get-Content (Join-Path $repo '.env') | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
    }
}
# decode the child's UTF-8 output as UTF-8 so Korean text is kept in the log
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$mode = 'dry-run'
$pyArgs = @('--dry-run')
if ($Live) { $mode = 'LIVE'; $pyArgs = @() }
"---- $stamp mode=$mode" | Out-File -FilePath $log -Append -Encoding utf8
& python run_paper_trading_daily.py @pyArgs 2>&1 | ForEach-Object { "$_" } | Out-File -FilePath $log -Append -Encoding utf8
