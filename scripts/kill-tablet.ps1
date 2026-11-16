# 태블릿 엔진 원격 킬 요청(켜기 전용). Workers 에 요청을 남기면 태블릿이 1~2분 안에 KILL 을 켜고 매매방에 알린다.
#   .\scripts\kill-tablet.ps1          요청          .\scripts\kill-tablet.ps1 -Link   폰 즐겨찾기용 정지 링크 출력(한 번만 보관)
# 해제는 태블릿(Termux)에서 `python -m autotrader --config autotrader/autotrader.local.json resume-all`.
param([switch]$Link)
$k = (Get-Content "$HOME\stock-backup\cf-admin-key.txt" -Raw).Trim()
$h = @{ Authorization = "Bearer $k" }; $u = 'https://stock-alerts.wonithink.workers.dev'
if ($Link) { (Invoke-RestMethod "$u/kill/link" -Headers $h).link; return }
Invoke-RestMethod "$u/kill" -Method Post -Headers $h | ConvertTo-Json -Depth 4
