#!/bin/bash
# VM 상시 작업 설치를 한 줄로(2026-11-01). PowerShell 에서 그대로:
#
#   ssh -t stock-new 'bash ~/collector/deploy/install-unit.sh vi-forward'
#
# 하는 일: git pull → (방금 받은 최신 스크립트로 다시 실행) → deploy/<이름>.service·.timer 확인 →
#          서비스의 ReadWritePaths 폴더를 ubuntu 소유로 만들기 → /etc/systemd/system 에 복사 → daemon-reload →
#          타이머 enable --now → 서비스 1회 실행 → 결과·로그 끝 몇 줄.
# 이름은 deploy/ 에 있는 것만 받는다(경로·와일드카드 거부). 주문·실계좌 유닛은 이 스크립트로 설치하지 않는다.
set -euo pipefail
NAME="${1:-}"
REPO="$HOME/collector"
[[ "$NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "사용법: install-unit.sh <유닛 이름>  (예: vi-forward)"; exit 2; }
case "$NAME" in autotrader*|infinite-buying*|crypto-real-holdings*|kis-portfolio*|rv20*) echo "주문·실계좌 유닛은 이 스크립트로 설치하지 않는다: $NAME"; exit 2;; esac

if [ -z "${INSTALL_UNIT_PULLED:-}" ]; then
    git -C "$REPO" pull -q --ff-only
    INSTALL_UNIT_PULLED=1 exec bash "$REPO/deploy/install-unit.sh" "$NAME"     # 받은 최신본으로 다시
fi

SVC="$REPO/deploy/$NAME.service"
TMR="$REPO/deploy/$NAME.timer"
[ -f "$SVC" ] || { echo "없다: deploy/$NAME.service (git pull 뒤에도 — main 에 병합됐는지 확인)"; exit 1; }
echo "== $NAME · 커밋 $(git -C "$REPO" log --oneline -1)"

# ReadWritePaths 폴더가 없으면 ProtectSystem/ProtectHome 아래서 유닛이 시작조차 못 한다 — 미리 만든다.
for d in $(grep -E '^ReadWritePaths=' "$SVC" | cut -d= -f2-); do
    case "$d" in
        /home/ubuntu/*) mkdir -p "$d" ;;
        /srv/*) sudo install -d -o ubuntu -g ubuntu "$d" ;;
        *) echo "건너뜀(알 수 없는 위치): $d" ;;
    esac
done

FILES=("$SVC"); [ -f "$TMR" ] && FILES+=("$TMR")
sudo cp "${FILES[@]}" /etc/systemd/system/
sudo systemctl daemon-reload
if [ -f "$TMR" ]; then
    sudo systemctl enable --now "$NAME.timer"
fi
echo "== 1회 실행"
sudo systemctl start "$NAME.service" || true
systemctl show "$NAME.service" -p Result -p ExecMainStatus --no-pager
[ -f "$TMR" ] && systemctl list-timers "$NAME.timer" --no-pager | head -2
LOG=$(grep -E '^StandardOutput=append:' "$SVC" | cut -d: -f2- || true)
if [ -n "$LOG" ] && [ -f "$LOG" ]; then echo "== 로그 끝"; tail -3 "$LOG"; else journalctl -u "$NAME" -n 5 --no-pager; fi
