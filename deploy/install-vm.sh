#!/usr/bin/env bash
# install-vm.sh — 분봉 Broad 수집을 상시화한다 (MN-1.0 §9)
#
# 이것이 실질적 완성 지점이다. 1회 수집은 한 번 도는 것이고, 상시화가 되어야
# "오늘 안 받은 하루는 246영업일 뒤 영영 사라진다"는 문제가 끝난다.
#
# 무엇을 만드는가
#   systemd timer   하루 2회 수집 (2회차는 1회차 실패분을 resume)
#   cron            alive-monitor (수집이 멈춘 것을 늦게 아는 문제를 막는다)
#   logrotate       로그가 1GB VM의 디스크를 먹지 않게
#
# 무엇을 건드리지 않는가
#   /home/ubuntu/stock (기존 모니터) · 그 venv · 그 cron · 시스템 시간대
#
# 멱등하다. 여러 번 돌려도 같은 상태가 된다.
#
# 사용:
#   bash deploy/install-vm.sh              설치 · 갱신
#   bash deploy/install-vm.sh --dry-run    무엇을 할지만 보여준다
#   bash deploy/install-vm.sh --uninstall  타이머·cron을 걷어낸다 (데이터는 둔다)

set -euo pipefail

REPO="${COLLECTOR_REPO:-$HOME/collector}"
VENV="${COLLECTOR_VENV:-$HOME/collector-venv}"
PY="$VENV/bin/python3"
ENVFILE="$VENV/collector.env"
LOGDIR="$VENV/logs"
RAW="${MINUTE_RAW_ROOT:-$HOME/minute-raw}"
UNIT_DIR=/etc/systemd/system
SERVICE=minute-collect.service
TIMER=minute-collect.timer
CRON_TAG="# minute-alive-monitor (MN-1.0)"

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
say "분봉 수집 상시화  $(date '+%Y-%m-%d %H:%M:%S %Z')"
say "repo   $REPO"
say "venv   $VENV"
say "raw    $RAW"
echo

# ---------------------------------------------------------------- 사전 확인
# 없는 것을 만들어 주지 않는다. 여기서 조용히 만들면 잘못된 곳에 설치된다.
for p in "$REPO/scripts/run-minute-daily.py" "$PY"; do
  [ -e "$p" ] || { say "[중단] 없다: $p"; exit 1; }
done

if [ "$UNINSTALL" = 1 ]; then
  say "제거한다 (수집한 데이터와 manifest는 그대로 둔다)"
  run "sudo systemctl disable --now $TIMER 2>/dev/null || true"
  run "sudo rm -f $UNIT_DIR/$TIMER $UNIT_DIR/$SERVICE"
  run "sudo systemctl daemon-reload"
  run "crontab -l 2>/dev/null | grep -v '$CRON_TAG' | grep -v alive-monitor.py | crontab - || true"
  echo; say "제거 완료"; echo
  exit 0
fi

if [ ! -f "$VENV/.env" ]; then
  say "[중단] $VENV/.env 가 없다. 먼저 키를 넣는다:"
  say "  KIS_ENV_PATH=$VENV/.env $PY $REPO/scripts/setup-kis-key.py --show"
  exit 1
fi

# ---------------------------------------------------------------- 시각 환산
# 이 머신의 시간대를 바꾸지 않는다. 기존 모니터가 그 시간대를 전제할 수 있다.
# 대신 KST 기준 시각을 로컬 벽시계로 옮겨 유닛에 박는다.
utc_to_local() {   # $1 = HH:MM (UTC)
  date -d "$(date -u +%Y-%m-%d)T$1:00Z" +%H:%M
}
RUN1="$(utc_to_local 07:10)"   # 16:10 KST
RUN2="$(utc_to_local 08:40)"   # 17:40 KST
MON_HM="$(utc_to_local 09:10)" # 18:10 KST
say "시간대   $(date +%Z) (offset $(date +%z))"
say "수집     $RUN1 · $RUN2 로컬  (= 16:10 · 17:40 KST)"
say "감시     $MON_HM 로컬  (= 18:10 KST · deadline 18:00)"
echo

# ---------------------------------------------------------------- 디렉터리
run "mkdir -p '$LOGDIR' '$RAW'"

# ---------------------------------------------------------------- 환경 파일
# 시크릿은 여기 넣지 않는다. 앱키는 $VENV/.env 에만 있고 KIS_ENV_PATH로 가리킨다.
# systemd EnvironmentFile은 셸 확장을 하지 않으므로 절대 경로만 쓴다.
ENVBODY="# minute collector — install-vm.sh가 생성한다. 시크릿을 넣지 않는다.
MINUTE_RAW_ROOT=$RAW
MINUTE_STATE_DIR=$RAW/_state
MINUTE_MANIFEST_DIR=$REPO/data/backfill/minute/manifest
KIS_ENV_PATH=$VENV/.env
KIS_TOKEN_CACHE=$VENV/.token_cache_kis.json
PYTHONUNBUFFERED=1
"
if [ "$DRY" = 1 ]; then
  printf '  [dry] write %s\n' "$ENVFILE"
else
  printf '%s' "$ENVBODY" > "$ENVFILE"
  chmod 600 "$ENVFILE"
fi
say "환경     $ENVFILE"

# ---------------------------------------------------------------- 유닛
render() {   # $1 = 원본, $2 = 대상
  sed -e "s|@REPO@|$REPO|g" -e "s|@USER@|$(id -un)|g" -e "s|@PY@|$PY|g" \
      -e "s|@ENVFILE@|$ENVFILE|g" -e "s|@LOGDIR@|$LOGDIR|g" \
      -e "s|@RUN1@|$RUN1|g" -e "s|@RUN2@|$RUN2|g" "$1" > "$2"
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

# ---------------------------------------------------------------- logrotate
LR="/etc/logrotate.d/minute-collect"
LRBODY="$LOGDIR/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
"
if [ "$DRY" = 1 ]; then
  printf '  [dry] write %s\n' "$LR"
else
  printf '%s' "$LRBODY" | sudo tee "$LR" >/dev/null
fi
say "로테이트 $LR"

# ---------------------------------------------------------------- cron (감시)
# 감시기는 systemd가 아니라 cron에 둔다. 수집 유닛이 통째로 죽어도(유닛 파일
# 오류·daemon-reload 실패) 감시는 그것과 다른 경로로 살아 있어야 한다.
# 종료 코드 0=OK 1=STALE 2=PENDING.
CRON_LINE="${MON_HM#*:} ${MON_HM%:*} * * * MINUTE_MANIFEST_DIR=$REPO/data/backfill/minute/manifest MINUTE_STATE_DIR=$RAW/_state $PY $REPO/scripts/alive-monitor.py --deadline 18:00 --json >> $LOGDIR/alive-monitor.log 2>&1 $CRON_TAG"

if [ "$DRY" = 1 ]; then
  printf '  [dry] crontab += %s\n' "$CRON_LINE"
else
  ( crontab -l 2>/dev/null | grep -v "$CRON_TAG" || true; echo "$CRON_LINE" ) \
    | crontab -
fi
say "cron     $MON_HM 로컬"

# ---------------------------------------------------------------- 확인
echo
say "확인"
say "  systemctl list-timers $TIMER"
say "  systemctl start $SERVICE   # 지금 한 번 돌린다"
say "  journalctl -u $SERVICE -n 50"
say "  tail -f $LOGDIR/minute-collect.log"
say "  $PY $REPO/scripts/alive-monitor.py --deadline 18:00"
echo
