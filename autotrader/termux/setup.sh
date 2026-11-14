#!/data/data/com.termux/files/usr/bin/bash
# 폰(Termux) 모의 시험 설치 — 키 없음 · 주문 없음. 저장소 일부(autotrader·config·연구 엔진 일부, 약 15MB)만 받는다.
# 사용: bash setup.sh      다시 돌려도 안전(이미 있으면 갱신만). 체크리스트: docs/control/폰-Termux-모의시험-체크리스트-2026-11-14.md
set -eu
REPO="https://github.com/wonithink-a11y/stock.git"
DIR="$HOME/stock"

pkg update -y
pkg install -y python git nano
pip install requests tzdata          # 표준 라이브러리 밖에서 엔진이 쓰는 것(requests) + 시간대 자료

if [ ! -d "$DIR/.git" ]; then
  git clone --depth 1 --filter=blob:none --sparse "$REPO" "$DIR"
fi
cd "$DIR"
git sparse-checkout set --no-cone '/autotrader/' '/config/' '/research/strategy-lab/*.py' '/research/strategy-lab/engine/'
git pull --ff-only

[ -f autotrader/autotrader.local.json ] || cp autotrader/config.example.json autotrader/autotrader.local.json
if [ ! -f .env ]; then
  umask 077                           # 키 파일은 본인만 읽는다
  cat > .env <<'EOF'
# 모의투자 키만 넣는다(실계좌·업비트 키 금지). nano .env 로 = 뒤를 채운다. 이 파일은 저장소·대화·메신저에 올리지 않는다.
KIS_VTS_APP_KEY=
KIS_VTS_APP_SECRET=
KIS_VTS_ACCOUNT_NO=
EOF
  chmod 600 .env
fi

echo
echo "설치 끝. 다음: nano ~/stock/.env 에 모의 키 입력 → cd ~/stock && python -m autotrader check-config"
