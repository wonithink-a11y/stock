#!/data/data/com.termux/files/usr/bin/bash
# 업비트 투자유의·주의 forward 기록(collect_upbit_market_events.py)을 매시 :07 에 부르는 반복 실행(서버의 upbit-market-events.timer 대신).
# 키 없음 · 주문 없음(업비트 공개 API 만). 상태·원장: ~/.upbit-events (state.json · events.jsonl · snapshots-*/prices-*.jsonl — 판정 원장이라 지우지 않는다).
# 시험: `bash run-upbit-loop.sh --once` (한 번만 실행하고 끝). 멈추기: pkill -f run-upbit-loop.sh
# 처음 켜면 state.json 이 없어 '첫 실행'이다 — 켜져 있던 플래그는 사건으로 세지 않는다(새 forward 표본 시작점).
export TZ=Asia/Seoul
cd "$HOME/stock" || exit 1
mkdir -p logs
termux-wake-lock 2>/dev/null || true
export UPBIT_EVENTS_DIR="$HOME/.upbit-events"
run() {
  echo "$(date '+%F %T')" >> logs/upbit-events.log
  python research/strategy-lab/collect_upbit_market_events.py >> logs/upbit-events.log 2>&1
  [ "$(stat -c%s logs/upbit-events.log 2>/dev/null || echo 0)" -gt 2000000 ] && tail -c 500000 logs/upbit-events.log > logs/upbit-events.log.tmp && mv logs/upbit-events.log.tmp logs/upbit-events.log
}
[ "${1:-}" = "--once" ] && { run; exit 0; }
while true; do
  run
  now=$(date +%s)                                   # 다음 :07 까지 잔다(서버 타이머와 같은 분)
  next=$(( (now / 3600) * 3600 + 7 * 60 ))
  [ "$next" -le "$now" ] && next=$(( next + 3600 ))
  sleep $(( next - now ))
done
