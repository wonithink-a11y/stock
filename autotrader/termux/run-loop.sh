#!/data/data/com.termux/files/usr/bin/bash
# 5분마다 autotrader run-due 를 부르는 반복 실행(서버의 systemd 타이머 대신). 기본은 dry-run(주문 없음).
# 모의 주문은 `bash run-loop.sh --execute` 로 직접 켠 때만, 그것도 프로필 파일이 "auto":"execute" 인 것만 나간다.
# 이 스크립트는 실전 키·AUTOTRADER_ALLOW_LIVE 를 건드리지 않는다. 멈추기: pkill -f run-loop.sh
export TZ=Asia/Seoul                          # 로그 시각을 한국 시간으로(Termux 기본 시간대가 한국이 아닐 수 있다 — 2026-11-15 태블릿에서 12시간 어긋남)
cd "$HOME/stock" || exit 1
mkdir -p logs
termux-wake-lock 2>/dev/null || true         # 화면이 꺼져도 CPU 를 재우지 않는다
# 엔진 멈춤 알림용 하트비트: .env 에 ALERTS_URL(https://stock-alerts.…workers.dev)·ALERTS_ADMIN_KEY 가 있을 때만 5분마다 POST. 키는 명령줄에 안 나온다.
ALERTS_URL=$(grep -m1 '^ALERTS_URL=' .env 2>/dev/null | cut -d= -f2-)
ALERTS_KEY=$(grep -m1 '^ALERTS_ADMIN_KEY=' .env 2>/dev/null | cut -d= -f2-)
hb() { [ -n "$ALERTS_URL" ] && [ -n "$ALERTS_KEY" ] && printf 'header = "Authorization: Bearer %s"\n' "$ALERTS_KEY" | curl -s --max-time 10 -K - -X POST "$ALERTS_URL/hb" > /dev/null; return 0; }
# 원격 킬: Workers 에 요청(PC·정지 링크)이 있으면 KILL 을 기본+모든 프로필에 켜고 ack 한다. 켜기만 한다 — 해제는 사람이 `resume-all`.
# 매분 부르므로 주문 전 1~2분 안에 닿는다. 켜기에 실패하면 ack 하지 않아 다음 분에 다시 시도한다.
killcheck() {
  [ -n "$ALERTS_URL" ] && [ -n "$ALERTS_KEY" ] || return 0
  r=$(printf 'header = "Authorization: Bearer %s"\n' "$ALERTS_KEY" | curl -s --max-time 10 -K - "$ALERTS_URL/kill")
  case "$r" in *'"kill":{'*)
    echo "$(date '+%F %T') 원격 킬 요청 수신" >> logs/heartbeat.log
    if python -m autotrader --config autotrader/autotrader.local.json kill-all >> logs/autotrader.log 2>&1; then
      printf 'header = "Authorization: Bearer %s"\n' "$ALERTS_KEY" | curl -s --max-time 10 -K - -X POST "$ALERTS_URL/kill/ack" > /dev/null
    fi;; esac
  return 0
}
while true; do
  killcheck                                     # 주문(run-due) 직전에도 한 번 본다
  python -m autotrader --config autotrader/autotrader.local.json run-due "$@" >> logs/autotrader.log 2>&1
  # 5분마다 한 줄 — 멈춘 시각과 공인 IP 가 바뀐 시각을 여기서 본다(no-net = 인터넷 끊김). 이 파일은 폰에만 있고 커밋되지 않는다.
  echo "$(date '+%F %T') $(curl -s --max-time 5 https://api.ipify.org || echo no-net)" >> logs/heartbeat.log
  hb
  for f in logs/autotrader.log logs/heartbeat.log; do   # 로그가 5MB 를 넘으면 뒤쪽 1MB 만 남긴다
    [ "$(stat -c%s "$f" 2>/dev/null || echo 0)" -gt 5000000 ] && tail -c 1000000 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  done
  for i in 1 2 3 4 5; do sleep 60; killcheck; done      # 5분 간격은 그대로, 킬 요청만 매분 확인
done
