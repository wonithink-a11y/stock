# PC 가 켜져 있을 때 GCP 서버 상태를 받아 온다(Tailscale 필요). 14개만 남긴다. 실패하면 조용히 종료(다음에 다시).
# 받는 곳: $HOME\stock-backup\gcp\gcp-state-날짜.tgz — 저장소 밖(민감 정보 포함: 웹 인증 해시·카카오 토큰). 커밋·업로드 금지.
# 키: $HOME\.ssh\stock-gcp-backup (서버 authorized_keys 에서 이 백업 명령만 실행 가능하게 묶여 있다)
$ErrorActionPreference = 'Stop'
$dir = Join-Path $HOME 'stock-backup\gcp'
New-Item -ItemType Directory -Force $dir | Out-Null
$out = Join-Path $dir ("gcp-state-{0}.tgz" -f (Get-Date -Format 'yyyyMMdd-HHmm'))
$tmp = "$out.part"
$key = Join-Path $HOME '.ssh\stock-gcp-backup'
# 바이너리 안전: PowerShell 5.1 의 리디렉션은 바이트를 바꾸므로 cmd 의 > 를 쓴다
cmd /c "ssh -i `"$key`" -o BatchMode=yes -o ConnectTimeout=20 -o StrictHostKeyChecking=accept-new ubuntu@stock-gcp.tail4575b6.ts.net > `"$tmp`" 2>nul"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $tmp) -or (Get-Item $tmp).Length -lt 1024) {
    if (Test-Path $tmp) { Remove-Item $tmp }
    Write-Host '백업 실패(서버에 연결 안 됨?)'; exit 1
}
tar -tzf $tmp *> $null
if ($LASTEXITCODE -ne 0) { Remove-Item $tmp; Write-Host '백업 파일 손상'; exit 1 }
Move-Item $tmp $out
Get-ChildItem $dir -Filter 'gcp-state-*.tgz' | Sort-Object Name -Descending | Select-Object -Skip 14 | Remove-Item
Write-Host ("백업 완료: {0} ({1:N1} MB)" -f $out, ((Get-Item $out).Length / 1MB))
