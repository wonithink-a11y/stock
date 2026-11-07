# PC 에서 autotrader 웹·스냅샷 실행(서버 없이). 작업 스케줄러가 부른다.
#   -Mode web      웹 서버(127.0.0.1:8787, /autotrader) — .env 를 읽지 않는다(웹은 증권사 키를 못 보게)
#   -Mode snapshot 잔고·보유·미체결 읽기 전용 조회(주문 없음) — .env 의 KIS 키를 쓴다
# 외부 접속은 `tailscale serve`(사설망)로만. 설정·상태: autotrader\autotrader.local.json · autotrader\state\ (둘 다 gitignore)
param([Parameter(Mandatory)][ValidateSet('web', 'snapshot')][string]$Mode)
$repo = Split-Path $PSScriptRoot -Parent
Set-Location $repo
$env:PYTHONIOENCODING = 'utf-8'
$cfg = Join-Path $repo 'autotrader\autotrader.local.json'
$log = Join-Path $repo "autotrader\state\pc-$Mode.log"
if ($Mode -eq 'snapshot') {
    Get-Content (Join-Path $repo '.env') | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
        }
    }
    & python -m autotrader --config $cfg snapshot *>> $log
} else {
    & python -m autotrader --config $cfg serve --host 127.0.0.1 --port 8787 --base-path /autotrader *>> $log
}
