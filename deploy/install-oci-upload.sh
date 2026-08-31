#!/usr/bin/env bash
# install-oci-upload.sh — 분봉 raw+manifest OCI 업로드를 상시화한다 (MN-1.0 §1.1)
#
# install-vm.sh(수집 상시화)와 분리한 이유는 두 유닛이 다른 속도로 바뀌기
# 때문이다 - 업로드는 수집이 이미 통과시킨 manifest를 뒤따라가기만 하고,
# 실패해도(OCI 장애) 다음 실행이 이어받는다. 이미 잘 작동하는 install-vm.sh를
# 이 관심사 때문에 건드리지 않는다.
#
# 전제: install-vm.sh를 먼저 돌려 $VENV/collector.env(RAW·MANIFEST 경로)가
# 있어야 한다. 이 스크립트는 그 파일을 다시 만들지 않고 그대로 재사용한다 -
# 업로드가 읽는 MINUTE_RAW_ROOT·MINUTE_MANIFEST_DIR이 수집이 쓰는 것과
# 갈리면 안 되기 때문이다(같은 경로를 두 곳에서 따로 적으면 드리프트한다).
#
# 무엇을 건드리지 않는가
#   /home/ubuntu/stock (기존 모니터) · minute-collect.timer/.service · cron
#
# 멱등하다. 여러 번 돌려도 같은 상태가 된다.
#
# 사용:
#   bash deploy/install-oci-upload.sh              설치 · 갱신
#   bash deploy/install-oci-upload.sh --dry-run    무엇을 할지만 보여준다
#   bash deploy/install-oci-upload.sh --uninstall  타이머를 걷어낸다 (올라간 데이터는 그대로)

set -euo pipefail

REPO="${COLLECTOR_REPO:-$HOME/collector}"
VENV="${COLLECTOR_VENV:-$HOME/collector-venv}"
PY="$VENV/bin/python3"
ENVFILE="$VENV/collector.env"
LOGDIR="$VENV/logs"
NAMESPACE="${OCI_NAMESPACE:-ax4zjhxnmgyz}"
UNIT_DIR=/etc/systemd/system
SERVICE=minute-oci-upload.service
TIMER=minute-oci-upload.timer

DRY=0
UNINSTALL=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --uninstall) UNINSTALL=1 ;;
    *) echo "모르는 인자: $a" >&2; exit 2 ;;
  esac
done

say() { printf '  %s\n' "$*"; }
run() {
  if [ "$DRY" = 1 ]; then printf '  [dry] %s\n' "$*"; else eval "$@"; fi
}

echo
say "분봉 OCI 업로드 상시화  $(date '+%Y-%m-%d %H:%M:%S %Z')"
say "repo       $REPO"
say "venv       $VENV"
say "namespace  $NAMESPACE"
echo

# ---------------------------------------------------------------- 사전 확인
# 없는 것을 만들어 주지 않는다. 여기서 조용히 만들면 잘못된 곳에 설치된다.
for p in "$REPO/scripts/upload-minute-oci.py" "$PY" "$ENVFILE"; do
  [ -e "$p" ] || { say "[중단] 없다: $p"; \
    [ "$p" = "$ENVFILE" ] && say "       install-vm.sh를 먼저 돌린다"; exit 1; }
done

if [ "$UNINSTALL" = 1 ]; then
  say "제거한다 (OCI에 이미 올라간 데이터는 그대로 둔다)"
  run "sudo systemctl disable --now $TIMER 2>/dev/null || true"
  run "sudo rm -f $UNIT_DIR/$TIMER $UNIT_DIR/$SERVICE"
  run "sudo systemctl daemon-reload"
  echo; say "제거 완료"; echo
  exit 0
fi

# ---------------------------------------------------------------- 의존성
if ! "$PY" -c 'import oci' 2>/dev/null; then
  say "oci SDK가 없다 - 설치한다"
  run "'$PY' -m pip install --quiet oci"
fi

# ---------------------------------------------------------------- 시각 환산
# 이 머신의 시간대를 바꾸지 않는다. install-vm.sh와 같은 방식이다.
utc_to_local() {   # $1 = HH:MM (UTC)
  date -d "$(date -u +%Y-%m-%d)T$1:00Z" +%H:%M
}
RUN="$(utc_to_local 09:00)"   # 18:00 KST — 17:40 KST 수집 뒤
say "시간대   $(date +%Z) (offset $(date +%z))"
say "업로드   $RUN 로컬  (= 18:00 KST)"
echo

# ---------------------------------------------------------------- 유닛
render() {   # $1 = 원본, $2 = 대상
  sed -e "s|@REPO@|$REPO|g" -e "s|@USER@|$(id -un)|g" -e "s|@PY@|$PY|g" \
      -e "s|@ENVFILE@|$ENVFILE|g" -e "s|@LOGDIR@|$LOGDIR|g" \
      -e "s|@RUN@|$RUN|g" -e "s|@NAMESPACE@|$NAMESPACE|g" "$1" > "$2"
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
render "$REPO/deploy/$SERVICE" "$TMP/$SERVICE"
render "$REPO/deploy/$TIMER" "$TMP/$TIMER"

run "sudo install -m 0644 '$TMP/$SERVICE' '$UNIT_DIR/$SERVICE'"
run "sudo install -m 0644 '$TMP/$TIMER' '$UNIT_DIR/$TIMER'"
run "sudo systemctl daemon-reload"
run "sudo systemctl enable --now $TIMER"
say "유닛     $UNIT_DIR/$TIMER"

# minute-collect의 logrotate(*.log 와일드카드)가 이 로그도 이미 덮는다 -
# 별도 logrotate 항목을 만들지 않는다.

# ---------------------------------------------------------------- 확인
echo
say "확인"
say "  systemctl list-timers $TIMER"
say "  systemctl start $SERVICE   # 지금 한 번 돌린다"
say "  journalctl -u $SERVICE -n 50"
say "  tail -f $LOGDIR/minute-oci-upload.log"
echo
