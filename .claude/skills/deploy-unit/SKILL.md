---
name: deploy-unit
description: 새 VM 상시 작업(알림·수집·기록)을 systemd 서비스/타이머와 텔레그램 방 라우팅까지 묶어 배포하는 절차. "타이머로 돌려줘", "VM 에 올려줘", "알림 추가", "새 수집기 상시화", "systemd 유닛 만들어줘", "텔레그램으로 보내줘", "15분마다 돌게" 같은 말이 나오면 반드시 이 스킬을 쓴다. GitHub Actions cron 은 하루 몇 번만 돌고 최대 12시간 늦으니 분 단위가 필요한 건 VM 이다.
---

# 새 유닛 배포

Actions cron 은 지연이 크다(중앙 4~5시간, 최대 12시간). 분 단위·장중 작업은 VM 타이머로 만든다.
유닛 파일은 `deploy/` 에 두고 저장소가 정본이다. **설치는 sudo 가 필요해 사용자 몫**이다 (새 VM 유닛은 "확인받는" 항목).

## 1. 먼저 본보기를 연다

`deploy/news-alert.service` + `.timer` (oneshot 알림), `deploy/intraday-alert.*`, `deploy/yt-digest.*` 중 가장 닮은 것을 복사해 시작한다. 처음부터 쓰지 않는다.

## 2. 서비스 파일 규칙

```ini
[Unit]
Description=...
After=network-online.target
Wants=network-online.target
OnFailure=unit-failure-notify@%n.service      # 필수. 장애 방으로 간다

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/collector
EnvironmentFile=/home/ubuntu/collector-venv/.env   # 시크릿은 여기. 유닛 파일에 쓰지 않는다
Environment=...                                # 비시크릿 설정만
ExecStart=/home/ubuntu/collector-venv/bin/python3 /home/ubuntu/collector/scripts/<이름>.py   # node 면 /usr/bin/node
TimeoutStartSec=...
NoNewPrivileges=yes
PrivateTmp=yes
```

- 상태·원장은 `~/collector-venv/<이름>/` 에 둔다 (저장소 밖, 커밋 안 함). 지우면 중복 알림이 쏟아질 수 있으니 주석에 적는다.
- `unit-failure-notify@.service` 자신에는 OnFailure 를 걸지 않는다 (서로 무한 호출).
- 남의 콘텐츠(유튜브·채널 글)는 VM 에만 두고 저장소·공개 대시보드에 올리지 않는다.
- 주문 코드가 있으면 기본 dry-run. 실주문 스위치를 켜는 것은 사용자 몫.

## 3. 타이머 파일 규칙

- 서비스와 같은 이름의 `.timer`, 상단에 `OnFailure=unit-failure-notify@%n.service`, `[Install] WantedBy=timers.target`.
- 시각은 KST 로 쓴다 (절대 규칙 3). `timedatectl` 로 VM 시간대를 확인하고, 주석에 "KST"를 적는다.
- 호출 예산을 주석에 계산해 둔다 (예: news-alert 하루 ≈ 11,800콜, 한도 25,000). 2분이 하한 — 실행이 겹치면 systemd 가 건너뛴다.
- 크립토는 휴장이 없어 `Mon..Fri` 가 아니라 매일.

## 4. 텔레그램 방 고르기 (같은 봇, 방 5개 + 장애 + 매매)

| 보낼 것 | 환경변수 |
|---|---|
| 장중 급등락·미국 8-K | `TELEGRAM_URGENT_CHAT_ID` |
| 마감 리포트 | `TELEGRAM_REPORT_CHAT_ID` |
| 유튜브 요약 | `TELEGRAM_VIDEO_CHAT_ID` |
| 뉴스·공시·D-day | `TELEGRAM_NEWS_CHAT_ID` |
| 등급 변동(Actions 전용) | `TELEGRAM_SCORE_CHAT_ID` |
| 장애 | `TELEGRAM_ALERT_CHAT_ID` (없으면 실패, 콘텐츠 방으로 안 샌다) |
| 로그인·주문·체결 | `TELEGRAM_TRADE_CHAT_ID` |

비어 있으면 1:1 방(`TELEGRAM_CHAT_ID`)으로 폴백한다. 새 알림이 어느 방이어야 하는지 모르겠으면 **내 권고를 붙여 사용자에게 묻는다**.
방이 슈퍼그룹이 되면 ID 가 바뀌어 끊긴다.

## 5. 설치 (사용자에게 명령 하나 — PowerShell 에 그대로 붙여 넣는 형태)

`deploy/install-unit.sh <이름>` 이 git pull → ReadWritePaths 폴더 만들기 → 유닛 복사 → daemon-reload → 타이머 enable --now → 1회 실행 → 로그 끝을 한 번에 한다.
**큰따옴표·heredoc 을 쓰지 않는다**(PowerShell 이 ssh '…' 안의 큰따옴표를 지운다, 11-01 실측).

```
ssh -t stock-new 'bash ~/collector/deploy/install-unit.sh <이름>'
```

설치 스크립트가 VM 에 아직 없을 때(그날 06:30 pull 전에 처음 쓰는 경우)만 앞에 pull 을 붙인다:
`ssh -t stock-new 'cd ~/collector && git pull -q && bash deploy/install-unit.sh <이름>'`.
주문·실계좌 유닛(autotrader·rv20·infinite-buying·kis-portfolio·crypto-real-holdings)은 스크립트가 거부한다 — 그건 수동 절차대로.
설치 뒤 확인은 클라우드에서 `python scripts/research-data.py status <이름>`.

`.env` 에 필요한 키(네이버·DART·텔레그램 방 ID 등)는 사용자가 직접 넣는다. 내가 키 값을 다루지 않는다.

## 6. 확인 (내가 ssh stock-new 로 읽기 전용)

- `systemctl list-timers | grep <이름>` 에 NEXT 가 잡혔는가.
- 1회 실행 로그에 에러 없음, 새 방에 **실제로 도착**했는가. 도착은 사용자가 봐야 안다 — 확인 전이면 인수인계에 "미확인"으로 적는다.
- 장애 알림 시험은 일부러 실패를 만들지 않는다. 알림 이름이 `*.timer` 로 오면 파일이 깨진 것.

## 7. 닫기

- 새 환경변수·유닛이 있으면 `docs/control/` 인수인계 표(무엇↔환경변수↔실행 위치)에 한 줄.
- 감시 대상 유닛이 늘면 `vm-check` 스킬의 기대 스케줄 표에 한 행 추가.
- Actions 쪽 실패 알림이 필요하면 `notify-failure.yml` 대상 목록(현재 12개)에 추가 — 단 10분 주기처럼 잦은 것은 '성공→실패' 전이에만.

## 8. GCP 임시 서버일 때 (OCI 정지 중 — 2026-11-07~, 복구되면 이 절 삭제)

위 절차의 `ssh stock-new` 는 **안 붙는다**. 서버는 GCP e2-micro, 접속은 사용자의 브라우저 SSH 창뿐이고 Claude 는 접속·확인 불가 — 명령은 사용자가 치고 화면 캡처로 확인한다.

- **계정**: 기본 로그인은 `wonithink`, 서비스·파일은 `ubuntu`. `~` 는 `wonithink` 홈으로 풀리므로 **`sudo -iu ubuntu bash /home/ubuntu/...` 전체 경로**.
- **코드 반영**: `~/collector` 는 main 만 받은 얕은 복제라 브랜치 checkout 불가, `collector-pull` 도 main 을 따라간다. 병합 전 파일은
  `sudo -iu ubuntu bash -c 'cd ~/collector && git fetch -q --depth 1 origin <브랜치> && git checkout FETCH_HEAD -- <파일들>'`
- **설치**: `sudo -iu ubuntu bash /home/ubuntu/collector/deploy/install-unit.sh <이름>` → `systemctl list-timers <이름>.timer --no-pager`.
- **확인**: 스크립트에 `--test`(전송 경로만 확인, 상태 불변) 옵션을 둔다. 수동 실행은 `.env` 를 못 읽으므로
  `sudo systemd-run --wait --pipe -p User=ubuntu -p EnvironmentFile=/home/ubuntu/collector-venv/.env -p Environment=... /home/ubuntu/collector-venv/bin/python3 /home/ubuntu/collector/scripts/<x>.py --test`
  (`. .env` 로 셸에 읽지 않는다 — 이름 없는 줄이 있으면 오류).
- **키·토큰 옮기기**: 채팅에 값을 붙이지 않는다. PC PowerShell 에서 `Select-String '^이름' .env | ForEach-Object Line | Set-Clipboard` → 서버 SSH 에서 `sudo -iu ubuntu bash -c 'cat >> /home/ubuntu/collector-venv/.env'` 후 Ctrl+V · Enter · Ctrl+D. 파일(`token.json` 등)은 `cat > 파일 && chmod 600`. 넣은 뒤 **`grep -o '^이름='` 으로 이름만 확인**(붙여넣는 순간 값이 화면에 찍히니 스크린샷을 보낼 때 가린다).
- **함정**: 브라우저 SSH 에 여러 줄 코드를 붙이면 줄바꿈이 깨진다 → 한 줄 명령이나 스크립트 옵션으로. PC PowerShell 의 `sudo` 는 윈도우 sudo 라 서버 명령을 치면 오류 — 서버 명령은 SSH 창에서. 새 패키지 누락은 실행해야 드러난다(jwt·scipy → `gcp-bootstrap.sh`).
- **복구 시**: GCP 에 올린 유닛은 `disable --now` 로 먼저 끈다(같은 봇·같은 모의 계좌 이중 실행 방지). 목록은 인수인계 11-07 §3·§10.
