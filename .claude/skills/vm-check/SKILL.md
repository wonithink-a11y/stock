---
name: vm-check
description: 작업 VM(수집·페이퍼 엔진·RV20·autotrader·알림 타이머) 상태 점검 절차. "VM 확인해줘", "타이머 돌고 있어?", "서버 로그 봐줘", "알림이 안 와", "어제 돌았나", "systemctl", "ssh", "VM pull", "장애 방에 뭐 떴어" 같은 말이 나오면 반드시 이 스킬을 쓴다. VM 에 붙기 전에 먼저 읽는다 — 엉뚱한 기계에 붙으면 오류 없이 "파일이 없다"로 나온다.
---

# VM 점검

## 0. 어느 기계인가 (가장 먼저)

```
ssh stock-new   hostname: stock          ← 작업 VM. 전부 여기다
ssh stock       hostname: stock-monitor  ← 옛 감시 대시보드. 폐기 시험 중, stock.service 는 일부러 정지
```

문서가 말하는 "VM(`stock`)"은 hostname 기준이라 **접속은 `ssh stock-new`** 다. 붙자마자 `hostname` 이 `stock` 인지 본다.
`stock-monitor` 가 나오면 잘못 붙은 것이다 — 거기서 "타이머 없음"이 나와도 고장이 아니다.

## 1. 읽기 전용 점검 (바로 해도 된다)

한 번의 ssh 로 묶어서 부른다 (턴·토큰 절약). 필요하면 `ssh stock-new '<명령>'`.

```bash
hostname; date
systemctl --failed --no-legend                 # 비어 있어야 정상
systemctl list-timers --no-pager | head -40    # NEXT/LAST 가 기대대로인가
cd ~/collector && git log --oneline -1 && git status -sb | head -3   # pull 됐나
df -h / | tail -1; free -m | sed -n 2p
```

유닛 하나가 의심되면: `journalctl -u <유닛> -n 30 --no-pager` · `systemctl status <유닛> --no-pager`.
RV20 선물: `tail -30 ~/collector-venv/logs/rv20-futures-paper-order.log`.

## 2. 무엇이 정상인가 (기대 스케줄)

| 유닛 | 언제 | 확인 포인트 |
|---|---|---|
| collector-pull | 매일 06:30 | 최신 커밋이 main 과 같은가 |
| rv20-futures-paper-order | 평일 09:05 | 로그에 percentile·배수·주문번호 또는 "주문 없음", 종료 15초 안팎 |
| crypto-upshock-paper | 매일 09:05 | 중복 매수 없음 |
| us-universe-snapshot | 화~토 07:30 | 스냅샷 날짜 증가 |
| news-alert | 평일 08~18시 | 상태 `~/collector-venv/news` |
| intraday-alert | 장중 10분 | 상태 `~/collector-venv/intraday` |
| orderflow-collect | 평일 08:49~15:31 | `~/orderflow-raw` 건수만 본다 (값은 2027-04 까지 열지 않는다) |
| yt-digest / kakao-report / channels-feed | 20분 / 10분 / 15분 | 실패 알림이 없으면 정상 |
| autotrader / paper-trading-poll | 5분 / 10분 | autotrader 는 지금 dry-run — 주문 0 이 정상 |

**일부러 꺼 둔 것(고장 아님)**: `infinite-buying-vts.timer`(09-22 의도적 disabled, 무한매수는 지금 어디서도 안 돈다) ·
옛 `stock.service`(stock-monitor). 이걸 켜자고 제안하지 않는다.

## 3. 함정

- **알림 이름이 `*.timer` 면 유닛 파일이 깨진 것**(로드 실패)이지 실행 실패가 아니다. 장애 방(`주식 알림`)에 뭐가 뜨면 무조건 고장이다.
- **VM 실패는 Actions 에 안 나타난다.** 워크플로 녹색과 데이터 존재는 다르다.
- 로컬 pyarrow 와 VM pyarrow 17 이 달라, 로컬 초록이 VM 초록이 아니다 (`scripts/check-vm-readiness.py`).
- 타이머 `--execute` 는 프로필 공용이라 한 프로필의 auto=execute 가 다른 전략도 켠다 — 주문 관련 유닛은 건드리지 않는다.
- OpenDART 는 동시 2개 이하. 점검하면서 수집을 몰아 돌리지 않는다.

## 4. 내가 하는 것 / 사용자 몫

- 내가: 위 읽기 전용 점검, `git pull`, 이미 등록된 유닛의 1회 실행·재시작(sudo 가 필요 없을 때).
- 사용자 몫: `sudo` 가 필요한 변경(유닛 설치·enable·edit), `.env` 에 키 넣기, 실계좌 주문 스위치·킬 해제(패스키), nginx·인증서.
  필요하면 한 줄씩 복붙할 수 있게 bash 한 블록에 명령 하나로 건넨다.

## 5. 보고

"이상 없음 — failed 0, 타이머 n개 정상, 최신 커밋 xxxx" 한 줄. 이상이면 유닛 이름·마지막 로그 몇 줄·추정 원인·권고 한 가지.
