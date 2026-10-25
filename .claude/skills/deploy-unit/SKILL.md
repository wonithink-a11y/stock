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

## 5. 설치 (사용자에게 한 줄씩, 한 블록에 명령 하나)

```bash
cd ~/collector && git pull
```
```bash
sudo cp deploy/<이름>.service deploy/<이름>.timer /etc/systemd/system/ && sudo systemctl daemon-reload
```
```bash
sudo systemctl enable --now <이름>.timer
```
```bash
sudo systemctl start <이름>.service && journalctl -u <이름> -n 30 --no-pager
```

`.env` 에 필요한 키(네이버·DART·텔레그램 방 ID 등)는 사용자가 직접 넣는다. 내가 키 값을 다루지 않는다.

## 6. 확인 (내가 ssh stock-new 로 읽기 전용)

- `systemctl list-timers | grep <이름>` 에 NEXT 가 잡혔는가.
- 1회 실행 로그에 에러 없음, 새 방에 **실제로 도착**했는가. 도착은 사용자가 봐야 안다 — 확인 전이면 인수인계에 "미확인"으로 적는다.
- 장애 알림 시험은 일부러 실패를 만들지 않는다. 알림 이름이 `*.timer` 로 오면 파일이 깨진 것.

## 7. 닫기

- 새 환경변수·유닛이 있으면 `docs/control/` 인수인계 표(무엇↔환경변수↔실행 위치)에 한 줄.
- 감시 대상 유닛이 늘면 `vm-check` 스킬의 기대 스케줄 표에 한 행 추가.
- Actions 쪽 실패 알림이 필요하면 `notify-failure.yml` 대상 목록(현재 12개)에 추가 — 단 10분 주기처럼 잦은 것은 '성공→실패' 전이에만.
