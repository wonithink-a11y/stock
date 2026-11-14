# stock-alerts — Cloudflare Workers 알림 (무료, 주문 없음)

PC·서버 없이 SVIX 신호 알림과 가격 목표 알림을 보낸다. 비용 원칙(CLAUDE.md 규칙 9) — **무료 요금제 안에서만**:
크론 트리거 계정당 5개(여기선 2개) · 요청 하루 10만 건 · KV 읽기 10만/쓰기 1천 per day · CPU 10ms/요청 (공식 문서 확인 2026-11-07).

| 크론 | 하는 일 |
|---|---|
| `*/5 * * * *` | 가격 목표 확인(국내 09:00~15:30 KST · 미국 정규장만 시세 조회) + **SVIX·SOXL 등락률**(전일 종가 대비 하루 한 번씩 **10%** 단계를 새로 넘거나 방향이 바뀔 때만 — 피로도 때문에 5% 가 아님) + **장중 VIX 20·25·30·35… 단계**(참고용 — 전일 종가의 단계보다 높은 단계에 닿을 때만, 매매 신호는 마감 기준) [텔레그램+카카오] |
| `10 22 * * 1-5` | SVIX 신호(UTC 22:10 = KST 07:10 화~토) — 신호가 바뀐 날만 알림 [텔레그램+카카오] |
| `40 6 * * 1-5` | 국내 마감 요약(KST 15:40) — 코스피200 · 코스닥150(KODEX 코스닥150 ETF 229200 로 대신, 지수 시세는 무료로 없음) [텔레그램만] |
| `10 21 * * 1-5` | 미국 마감 요약(KST 06:10) — S&P500 · 나스닥100 · SVIX · SOXL [텔레그램만] |

감시 종목·기준(`WATCH_US`·`MOVE_STEP`·`KR_INDEX`)은 코드 상단 상수다 — 바꾸려면 수정 후 `npx.cmd wrangler deploy`. 요약은 오늘 시세가 없으면(휴장) 보내지 않는다. 신규 로직 시험: `node cloudflare/alerts/test/unit.mjs`.

로직은 파이썬 정본(`scripts/vix-signal-alert.py`·`price-target-alert.py`)의 이식이다. 정본을 바꾸면
`node cloudflare/alerts/test/parity.mjs` 로 두 구현이 같은 결과를 내는지 다시 본다(8,631건 일치 — 신호 178건 포함).

## 배포 (PowerShell, `cd C:\Users\User\projects\stock\cloudflare\alerts`)

> ★ 이 PC 의 PowerShell 은 `npx.ps1` 실행 정책에 막힌다("스크립트를 실행할 수 없으므로") — 아래 `npx` 는 전부 **`npx.cmd`** 로 친다(정책 설정은 안 바꾼다).

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

## 손절선 이탈 1분 알림 · 엔진 멈춤 알림 (2026-11-15, 설계 `docs/control/손절알림-설계-2026-11-15.md`)

알림만 보낸다 — **주문 없음**. 크론은 `* * * * *` 하나가 매분 손절·엔진 멈춤을 보고, 5분마다 위 가격 목표·등락률 작업도 돌린다(무료 크론 5개 한도 안, 총 4개).

| 기능 | 동작 |
|---|---|
| 손절선 이탈 | 감시 목록(KV `stops`, 최대 30)의 시세가 손절선 이하(`dir:above` 면 이상)이면 **매매·보안방**(`TELEGRAM_TRADE_CHAT_ID`, 없으면 기본 방)에 알림. 처음 10분 매분, 이후 5분마다. 카카오(보조)는 처음·회복만 |
| 확인(알림 멈춤) | 메시지 끝의 서명 링크 → 버튼 한 번(GET 은 버튼만 보여 주고 POST 가 멈춘다 — 텔레그램 미리보기가 먼저 열어도 안 멈춘다). 가격이 회복되면 회복 알림 한 번 |
| 엔진 멈춤 | 감시 목록이 있는데 하트비트가 20분 넘게 없으면 알림(30분마다 반복, 복귀 시 한 번). 목록이 비면 조용 |

**관리 HTTP**(`Authorization: Bearer ADMIN_KEY`): `GET /stops` · `PUT /stops?src=engine|manual`(그 출처의 목록을 통째로 바꿈, 형식 `[{"market":"KR","symbol":"005930","name":"삼성전자","stop":70000,"note":"…"}]`) · `POST /hb` · `POST /test?chat=trade`(매매방 연결 시험).
시세: 국내 네이버 일봉(현재가), 미국 야후(마지막 체결이 15분 안일 때만 — 낡은 값은 건너뛴다). **무료 시세의 실제 지연은 미확인** — 며칠 증권사 화면과 비교해 2분 이내인지 기록한다.

### 배포(사용자, PowerShell, 저장소의 `cloudflare\alerts` 폴더에서)
1. `npx.cmd wrangler deploy` (크론이 매분으로 바뀐다).
2. 매매·보안방 번호를 시크릿으로(번호는 대화에 붙이지 않는다): `npx.cmd wrangler secret put TELEGRAM_TRADE_CHAT_ID` 후 프롬프트에 입력.
3. 시험: 관리 키(`stock-backup` 폴더의 `cf-admin-key.txt`)로 `POST /test?chat=trade` — 매매방에 도착하는지 눈으로 확인.
4. 태블릿(Termux) `~/stock/.env` 에 `ALERTS_URL=https://stock-alerts.wonithink.workers.dev` · `ALERTS_ADMIN_KEY=<위 관리 키>` 를 직접 입력하고 `run-loop.sh` 를 재시작 → 5분마다 `/hb`.
5. 처음엔 감시 목록을 비워 두고 하트비트만 확인(`GET /stops` 의 `hb`). 그 다음 모의 손절선을 `PUT /stops?src=manual` 로 넣어 알림·확인 링크를 시험.

시험: `node test/unit.mjs` · `node test/stops.mjs`(8) · `node test/worker.mjs`(7, 가짜 fetch·KV) · `node test/parity.mjs`.
