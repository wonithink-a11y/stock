#!/data/data/com.termux/files/usr/bin/bash
# SEC 8-K 공시 알림(scripts/edgar-8k-alert.py)을 15분마다 부르는 반복 실행(서버의 edgar-8k-alert.timer 대신).
# 기본은 실제 전송. 시험은 `bash run-edgar-loop.sh --dry-run`(보내지 않고 원장도 안 쓴다). 멈추기: pkill -f run-edgar-loop.sh
# 태블릿 ~/stock/.env 에 SEC_USER_AGENT(연락처 포함)·TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID 가 있어야 한다(사용자가 직접 입력).
# 처음 켜면 최근 피드 100건 중 알릴 항목이 한 번 몰려 나갈 수 있다(원장이 비어 있어서).
export TZ=Asia/Seoul
cd "$HOME/stock" || exit 1
mkdir -p logs
termux-wake-lock 2>/dev/null || true
envv() { grep -m1 "^$1=" .env 2>/dev/null | cut -d= -f2-; }      # run-loop.sh 처럼 필요한 키만 읽는다(.env 전체를 source 하지 않는다)
export SEC_USER_AGENT=$(envv SEC_USER_AGENT) TELEGRAM_BOT_TOKEN=$(envv TELEGRAM_BOT_TOKEN) TELEGRAM_CHAT_ID=$(envv TELEGRAM_CHAT_ID)
export EDGAR_STATE_DIR="$HOME/.edgar-state"
while true; do
  echo "$(date '+%F %T')" >> logs/edgar.log
  python scripts/edgar-8k-alert.py "$@" >> logs/edgar.log 2>&1
  [ "$(stat -c%s logs/edgar.log 2>/dev/null || echo 0)" -gt 2000000 ] && tail -c 500000 logs/edgar.log > logs/edgar.log.tmp && mv logs/edgar.log.tmp logs/edgar.log
  sleep 900
done
