# PC 에서 알림 스크립트를 돌린다(서버 없이). 저장소 .env 를 이 프로세스 환경으로 읽고 파이썬 스크립트를 실행한다.
#   powershell -ExecutionPolicy Bypass -File scripts\run-alert-pc.ps1 -Script vix-signal-alert.py [-ScriptArgs --test]
# 필요한 .env 키: TELEGRAM_BOT_TOKEN · TELEGRAM_URGENT_CHAT_ID(또는 TELEGRAM_CHAT_ID) · (카카오) KAKAO_REST_API_KEY · KAKAO_CLIENT_SECRET
# 상태·목표 파일은 스크립트 기본값(~\collector-venv\...) — 카카오 token.json 은 이미 거기 있다. PC 가 꺼져 있던 동안은 건너뛴다.
param([Parameter(Mandatory)][string]$Script, [string[]]$ScriptArgs = @())
$repo = Split-Path $PSScriptRoot -Parent
$env:PYTHONIOENCODING = 'utf-8'
Get-Content (Join-Path $repo '.env') | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim().Trim('"').Trim("'"), 'Process')
    }
}
& python (Join-Path $repo "scripts\$Script") @ScriptArgs
