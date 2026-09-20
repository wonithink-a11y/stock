#!/usr/bin/env bash
# KIS 모의 동시호가 1주 시험 — 일회성 예약(cron). 설계: docs/control/단기규칙-모의실행-설계-2026-09-20.md §5.
#
# VM(ubuntu 사용자)에서 한 번만 실행한다. sudo 가 필요 없다(사용자 crontab).
#   bash ~/collector/deploy/schedule-auction-probe.sh            # 예약 설치
#   bash ~/collector/deploy/schedule-auction-probe.sh --print    # 설치하지 않고 줄만 보여줌
#   bash ~/collector/deploy/schedule-auction-probe.sh --remove   # 예약 제거
#
# 예약 4개(KST): 월 2026-09-21 15:24 매수 1주 · 15:45 대조 · 화 09-22 08:45 매도 1주 · 09:05 대조(+예약 스스로 제거).
# cron 은 월·일만 지정하면 매년 돌기 때문에 각 줄이 **오늘 날짜를 검사**한다(다른 해에는 아무것도 안 함) — 게다가
# 마지막 줄이 끝나면 예약 줄을 전부 지운다. 주문 코드는 auction_order_probe_vts.py 의 안전장치(수량 1주 고정·시간창
# 밖 거절·매수→매도 순서 강제)를 그대로 쓴다. 결과는 ~/collector-venv/logs/auction-probe.log 와 data/paper/auction_test_vts.json.
set -euo pipefail
TAG="# auction-probe-2026-09"
PY=/home/ubuntu/collector-venv/bin/python3
DIR=/home/ubuntu/collector/research/strategy-lab
LOG=/home/ubuntu/collector-venv/logs/auction-probe.log
RUN="cd $DIR && $PY auction_order_probe_vts.py"

on() {  # $1=YYYY-MM-DD $2="분 시 일 월" $3=명령
  echo "$2 * test \$(date +\%F) = $1 && { $3; } >> $LOG 2>&1 $TAG"
}

lines() {
  on 2026-09-21 "24 15 21 9" "git -C /home/ubuntu/collector pull --ff-only -q; $RUN buy --execute"
  on 2026-09-21 "45 15 21 9" "$RUN verify"
  on 2026-09-22 "45 8 22 9"  "git -C /home/ubuntu/collector pull --ff-only -q; $RUN sell --execute"
  on 2026-09-22 "5 9 22 9"   "$RUN verify; crontab -l | grep -v 'auction-probe-2026-09' | crontab -"
}

case "${1:-}" in
  --print)  lines ;;
  --remove) (crontab -l 2>/dev/null | grep -v "auction-probe-2026-09" || true) | crontab - ; echo "예약 제거됨" ;;
  "")       (crontab -l 2>/dev/null | grep -v "auction-probe-2026-09" || true; lines) | crontab -
            echo "예약 설치됨:"; crontab -l | grep "auction-probe-2026-09" | cut -c1-110 ;;
  *)        echo "사용법: $0 [--print|--remove]"; exit 1 ;;
esac
