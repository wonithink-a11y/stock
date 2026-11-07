#!/usr/bin/env bash
# VM(stock-new)에서 체결 원장 진단·되살리기(fills-sync)를 **조회 전용**으로 한 번 돌린다.
# 브랜치 코드를 임시 작업트리에서 돌린다 — ~/collector 의 main 체크아웃·타이머는 건드리지 않는다. 주문은 나가지 않는다.
#
#   PC 에서 한 줄:
#   ssh stock-new "cd ~/collector && git fetch -q origin ccr-c32c9d34-v87x7r && git show FETCH_HEAD:scripts/vm-fills-sync.sh | bash"
#
# 바꿀 수 있는 값(환경변수): BR(브랜치) · PROFILE(기본 infbuy) · DAYS(기본 60, 최대 90)
set -euo pipefail
BR=${BR:-ccr-c32c9d34-v87x7r}
PROFILE=${PROFILE:-infbuy}
DAYS=${DAYS:-60}
REPO="$HOME/collector"
VENV="$HOME/collector-venv"
CONFIG="$VENV/autotrader/autotrader.local.json"

cd "$REPO"
git fetch -q origin "$BR"
WT=$(mktemp -d /tmp/fills-sync.XXXXXX)
rmdir "$WT"
git worktree add -q --detach "$WT" FETCH_HEAD
trap 'cd "$REPO"; git worktree remove --force "$WT" >/dev/null 2>&1 || true' EXIT
# 상태 폴더가 저장소 안(상대경로)이면 작업트리에서도 같은 곳을 보게 한다. .env 도 같은 이유.
[ -e "$REPO/autotrader/state" ] && ln -s "$REPO/autotrader/state" "$WT/autotrader/state"
[ -f "$REPO/.env" ] && ln -s "$REPO/.env" "$WT/.env"
cd "$WT"
export AUTOTRADER_ENV_FILE="$VENV/.env"
PY="$VENV/bin/python3"

echo "== 코드 $(git rev-parse --short HEAD) ($BR) · 프로필 $PROFILE · ${DAYS}일"
# 지금 원장 요약 + 백업(되돌리기: 백업 파일을 fills.json 으로 복사)
"$PY" - "$CONFIG" "$PROFILE" <<'PYEOF'
import json, shutil, sys
from datetime import datetime
from autotrader.config import load_profile, state_dir
from autotrader.engine import Ledger
cfg = load_profile(sys.argv[1], sys.argv[2])
sd = state_dir(cfg)
rows = [r for r in Ledger(sd).rows() if r.get("kind") == "order" and r.get("executed")]
days = sorted(r.get("day", "") for r in rows)
print(f"상태 폴더 {sd}")
print(f"원장 주문 {len(rows)}건 · 첫 {days[0] if days else '-'} · 마지막 {days[-1] if days else '-'} · 번호 예 {[r.get('orderNo') for r in rows[-3:]]}")
fp = sd / "fills.json"
if fp.exists():
    b = json.loads(fp.read_text(encoding="utf-8"))
    print(f"기존 fills.json: 체결 {len(b.get('fills', {}))}건 · 생성 {b.get('openedAt')} · 생성 전 주문(제외) {len(b.get('exclude', []))}")
    bak = fp.with_name(f"fills.json.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(fp, bak)
    print(f"백업 {bak}")
else:
    print("기존 fills.json 없음 — 스냅샷이 이 프로필의 체결을 한 번도 못 쌓았다")
PYEOF

echo "== fills-sync"
"$PY" -m autotrader --config "$CONFIG" --profile "$PROFILE" fills-sync --days "$DAYS" || echo "(fills-sync 종료코드 $? — 위 error 참고)"
echo "== 끝. 5분 스냅샷이 같은 파일을 동시에 쓰면 결과가 덮일 수 있다 — 체결 수가 다시 0 이면 한 번 더 돌린다."
