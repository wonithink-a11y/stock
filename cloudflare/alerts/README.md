# stock-alerts — Cloudflare Workers 알림 (무료, 주문 없음)

PC·서버 없이 SVIX 신호 알림과 가격 목표 알림을 보낸다. 비용 원칙(CLAUDE.md 규칙 9) — **무료 요금제 안에서만**:
크론 트리거 계정당 5개(여기선 2개) · 요청 하루 10만 건 · KV 읽기 10만/쓰기 1천 per day · CPU 10ms/요청 (공식 문서 확인 2026-11-07).

| 크론 | 하는 일 |
|---|---|
| `*/5 * * * *` | 가격 목표 확인(국내 09:00~15:30 KST · 미국 정규장만 시세 조회) |
| `10 22 * * 1-5` | SVIX 신호(UTC 22:10 = KST 07:10 화~토) — 신호가 바뀐 날만 알림 |

로직은 파이썬 정본(`scripts/vix-signal-alert.py`·`price-target-alert.py`)의 이식이다. 정본을 바꾸면
`node cloudflare/alerts/test/parity.mjs` 로 두 구현이 같은 결과를 내는지 다시 본다(8,631건 일치 — 신호 178건 포함).

## 배포 (PowerShell, `cd C:\Users\User\projects\stock\cloudflare\alerts`)

1. Cloudflare 무료 계정을 만든다(dash.cloudflare.com).
2. `npx wrangler login` — 브라우저에서 승인.
3. `npx wrangler kv namespace create ALERTS` — 출력되는 `id` 를 `wrangler.toml` 의 `REPLACE_WITH_KV_ID` 에 넣는다(비밀 아님).
4. 시크릿(PC `.env` 에서 값을 화면에 안 찍고 넣는다):
   ```powershell
   $e='C:\Users\User\projects\stock\.env'
   foreach($k in 'TELEGRAM_BOT_TOKEN','TELEGRAM_CHAT_ID','KAKAO_REST_API_KEY','KAKAO_CLIENT_SECRET'){ (Select-String "^$k=" $e).Line.Split('=',2)[1] | npx wrangler secret put $k }
   ```
5. 관리 키(관리 HTTP 용 — 파일에만 저장, 채팅에 올리지 않는다):
   ```powershell
   $b=New-Object byte[] 24; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); $k=($b|%{$_.ToString('x2')}) -join ''
   Set-Content $HOME\stock-backup\cf-admin-key.txt $k; $k | npx wrangler secret put ADMIN_KEY
   ```
6. 상태 넣기(카카오 토큰·빈 목표):
   ```powershell
   npx wrangler kv key put --binding=ALERTS kakao_token --path $HOME\collector-venv\kakao\token.json --remote
   npx wrangler kv key put --binding=ALERTS targets "[]" --remote
   ```
7. `npx wrangler deploy` — 주소 `https://stock-alerts.<계정>.workers.dev` 가 출력된다(처음이면 계정 서브도메인을 정하라고 묻는다).

## 관리 (Bearer 키 필요, 없으면 404)

```powershell
$k = Get-Content $HOME\stock-backup\cf-admin-key.txt; $h = @{Authorization="Bearer $k"}; $u = 'https://stock-alerts.<계정>.workers.dev'
Invoke-RestMethod -Method Post $u/test -Headers $h                    # 텔레그램·카카오 테스트 메시지
Invoke-RestMethod $u/targets -Headers $h                              # 목표 목록(fired 표시)
Invoke-RestMethod -Method Put $u/targets -Headers $h -ContentType 'application/json' -Body '[{"market":"KR","symbol":"005930","dir":"above","price":85000,"note":"메모"}]'
Invoke-RestMethod -Method Post $u/rearm -Headers $h                   # 울린 목표 다시 켜기
```
`market` KR|US, `dir` above|below. 목표는 KV 에만 있다(저장소 공개 — 매매 계획 노출 금지).

## 주의
- 카카오 갱신 토큰은 약 12월 중순 만료 — PC 에서 `scripts/send-kakao-report.py --login` 후 6번의 `kakao_token` 을 다시 넣는다.
- 텔레그램은 `TELEGRAM_CHAT_ID`(1:1 방)로 간다. 알림이 겹치므로 Workers 가 확인된 뒤 PC 작업 `stock-vix-alert`·`stock-price-alert` 는 끈다(`Disable-ScheduledTask`).
