---
name: pc-workers-ops
description: 서버 없이 도는 알림(Cloudflare Workers)과 PC 작업 스케줄러·PC 자동매매 웹을 고치고 배포하고 점검하는 절차. "알림 추가", "감시 종목 바꿔줘", "가격 목표 등록", "Workers 배포", "wrangler", "작업 스케줄러 등록·끄기", "PC 웹 켜줘", "카카오 토큰 갱신", "npx 안 돼", "액세스 거부" 같은 말이 나오면 반드시 이 스킬을 쓴다. 현재 구성은 docs/control/세션인수인계-2026-11-07-b.md.
---

# PC · Cloudflare Workers 운영

2026-11-07 OCI 정지·GCP 서버 중지 뒤의 구성이다(비용 0원, 규칙 9). **서버(VM)는 없다 — `ssh`·systemd 가 아니라 이 절차를 쓴다.**
서버를 다시 켜는 건 월 약 $3.6(외부 IP)이 재발하는 일이라 사용자 확인 후에만 한다.

| 일 | 어디 | 고치는 곳 |
|---|---|---|
| SVIX 신호·가격 목표·SVIX/SOXL 10% 단계·장중 VIX 단계·마감 요약 | Cloudflare Workers `stock-alerts` (크론 4개) | `cloudflare/alerts/src/`, 상수는 `index.js` 상단 |
| 자동매매 웹 + 모의 스냅샷 | 이 PC 작업 스케줄러 `stock-autotrader-web`·`-snapshot` | `scripts/run-autotrader-pc.ps1`, 상태 `autotrader\state\`(gitignore) |

## 1. Workers 를 고칠 때

1. 코드 수정(`src/core.js` 순수 로직 · `src/index.js` 크론·전송·관리 HTTP). 파이썬 정본(`scripts/vix-signal-alert.py`·`price-target-alert.py`)이 있는 로직은 정본과 같게 — 바꿨으면 `node cloudflare/alerts/test/parity.mjs`(8,631건), 새 로직은 `node cloudflare/alerts/test/unit.mjs` 에 시험을 더한다. **통과를 보고 배포한다.**
2. 크론을 늘리면 무료 한도(계정당 5개, 지금 4개)·요청당 외부 요청 50건·CPU 10ms 를 먼저 센다. 한도 숫자는 기억이 아니라 공식 문서로(`cost-check` 스킬).
3. 커밋 → 배포: `run_in_terminal` 로 `npx.cmd wrangler deploy`(cwd `cloudflare/alerts`) → `read_terminal` 로 `schedule:` 줄 4개와 `Deployed` 를 **내가 직접 읽어 확인**한다(사용자에게 스크린샷을 요구하지 않는다).
4. 주문은 없다. 알림 종류를 바꾸면 피로도(즉시는 소수·큰 폭만, 나머지는 하루 두 번 요약)를 먼저 따진다.

**사용자 몫(내가 안 하는 것)**: 시크릿 값 입력(`wrangler secret put` — PC `.env` 에서 파이프로 넣어 화면에 안 찍는다) · 카카오 `token.json` 업로드 · Cloudflare 계정·로그인.

**가격 목표 등록**(사용자가 종목·가격을 줄 때): 관리 키는 `C:\Users\User\stock-backup\cf-admin-key.txt`(채팅 금지). 사용자 PowerShell 에서
`Invoke-RestMethod -Method Put https://stock-alerts.wonithink.workers.dev/targets -Headers @{Authorization="Bearer $k"} -ContentType 'application/json' -Body '[{"market":"US","symbol":"SOXL","dir":"below","price":40,"note":"메모"}]'`
(`PUT` 은 목록 전체를 덮어쓴다 — 먼저 `GET /targets` 로 현재 목록을 받아 합친다). 가격은 사용자가 정한다 — 내가 골라 주지 않는다.

**카카오 토큰 갱신(≈ 12월 중순 만료)**: PC `python scripts/send-kakao-report.py --login` → `npx.cmd wrangler kv key put --binding=ALERTS kakao_token --path C:\Users\User\collector-venv\kakao\token.json --remote`.

## 2. PC 작업 스케줄러

- 켜짐: `stock-autotrader-web`(로그인 시)·`stock-autotrader-snapshot`(5분). 꺼짐: `stock-vix-alert`·`stock-price-alert`(Workers 와 중복)·`stock-gcp-backup`(서버가 꺼져 있음).
- **등록·활성/비활성은 관리자 PowerShell 이 필요하다**(일반 창은 "액세스가 거부되었습니다"). 옆 터미널 패널은 일반 권한이다 → 관리자 창에서 실행할 한 줄을 사용자에게 주고, 결과는 일반 창에서 `Get-ScheduledTask -TaskName 'stock-*'` 를 내가 읽어 확인한다. 관리자 창 화면은 내가 못 본다.
- 웹 확인: `Get-NetTCPConnection -LocalPort 8787 -State Listen`(읽기 전용) · 폰에서 `https://namwon.tail4575b6.ts.net/autotrader/`(Tailscale 앱 필요). **PC 가 절전이면 멈춘다.**

## 3. 함정 (이번에 다 물렸다)

- `npx` 는 PowerShell 실행 정책에 막힌다 → **`npx.cmd`**. `tailscale` 은 설치 직후 새 PowerShell 에서.
- **Git Bash 는 `/autotrader` 인자를 `C:/Program Files/Git/autotrader` 로 바꾼다**(MSYS) → `--base-path` 가 틀어져 404. 경로 인자가 있는 프로세스는 PowerShell 로.
- **관리자 창으로 알림·카카오 스크립트를 돌리면 `~\collector-venv\kakao\token.json` 이 관리자 소유로 바뀌어 일반 권한이 못 읽는다**(EPERM). 복구: 관리자 창에서 `takeown /f <파일>; icacls <파일> /grant 'namwon\user:F'`. 스크립트는 일반 창에서 돌린다.
- `run_in_terminal` 은 변수·파이프·괄호·여러 줄을 거부한다 — 복잡한 건 파일로 쓰고 실행하거나 사용자가 직접 친다. 한 번에 여러 `navigate` 를 배치하면 같은 탭을 덮어쓴다.
- 긴 heredoc 을 Bash 로 쓰면 깨지는 일이 있었다 → 파일은 Write 도구로.
- `.env` 에서 시크릿을 파이프로 넣으면 끝에 개행이 붙는다 — Workers 코드는 `trim()` 한다. 스크린샷에 값이 찍히지 않게 이름만 확인(`Select-String '^KEY' | Split('=')[0]`).
