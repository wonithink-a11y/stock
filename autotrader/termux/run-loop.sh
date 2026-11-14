#!/data/data/com.termux/files/usr/bin/bash
# 5분마다 autotrader run-due 를 부르는 반복 실행(서버의 systemd 타이머 대신). 기본은 dry-run(주문 없음).
# 모의 주문은 `bash run-loop.sh --execute` 로 직접 켠 때만, 그것도 프로필 파일이 "auto":"execute" 인 것만 나간다.
# 이 스크립트는 실전 키·AUTOTRADER_ALLOW_LIVE 를 건드리지 않는다. 멈추기: pkill -f run-loop.sh
cd "$HOME/stock" || exit 1
mkdir -p logs
termux-wake-lock 2>/dev/null || true         # 화면이 꺼져도 CPU 를 재우지 않는다
while true; do
  python -m autotrader --config autotrader/autotrader.local.json run-due "$@" >> logs/autotrader.log 2>&1
  date '+%F %T' >> logs/heartbeat.log          # 5분마다 한 줄 — 멈춘 시각을 여기서 본다
  for f in logs/autotrader.log logs/heartbeat.log; do   # 로그가 5MB 를 넘으면 뒤쪽 1MB 만 남긴다
    [ "$(stat -c%s "$f" 2>/dev/null || echo 0)" -gt 5000000 ] && tail -c 1000000 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  done
  sleep 300
done
