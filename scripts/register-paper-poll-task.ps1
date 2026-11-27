# Registers the Task Scheduler job stock-paper-poll (run in an ADMIN PowerShell). Weekdays from 09:05, every 10 minutes
# for 6h30m (until about 15:35 KST). ASCII only on purpose (Windows PowerShell 5.1 reads BOM-less files as ANSI).
#   default = a dry-run task (no orders). Re-register with -Live to send paper orders (same name overwrites).
#   Only registers; the existing stock-autotrader-* tasks are not touched.
# Usage (admin window):
#   powershell -ExecutionPolicy Bypass -File scripts\register-paper-poll-task.ps1          # dry-run
#   powershell -ExecutionPolicy Bypass -File scripts\register-paper-poll-task.ps1 -Live    # paper orders
#   Unregister-ScheduledTask -TaskName stock-paper-poll -Confirm:$false                     # remove
param([switch]$Live)
$repo = Split-Path $PSScriptRoot -Parent
$run = Join-Path $repo 'scripts\run-paper-poll-pc.ps1'
$arg = "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$run`""
if ($Live) { $arg = $arg + ' -Live' }
$action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument $arg
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At '09:05'
$rep = New-ScheduledTaskTrigger -Once -At '09:05' -RepetitionInterval (New-TimeSpan -Minutes 10) -RepetitionDuration (New-TimeSpan -Hours 6 -Minutes 30)
$trigger.Repetition = $rep.Repetition
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'stock-paper-poll' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Get-ScheduledTask -TaskName 'stock-paper-poll' | Select-Object TaskName, State
if ($Live) { 'mode: LIVE (paper orders)' } else { 'mode: dry-run' }
