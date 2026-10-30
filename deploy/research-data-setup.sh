#!/bin/bash
# 연구 데이터 통로(/research-data/) VM 설치 — 한 번만. 다시 돌려도 안전하다(키는 이미 있으면 그대로 둔다).
# 설계: docs/control/연구데이터-VM보관-설계-2026-10-30.md
#
#   ssh -t stock-new "cd ~/collector && git pull && sudo bash deploy/research-data-setup.sh"
#
# 하는 일: /srv/stock-data/{bundles,incoming} 만들기(ubuntu 소유) → 키 파일이 없으면 새 키 만들고 한 번 보여 주기 →
#          nginx 정본 2개를 백업 뒤 복사 → nginx -t 실패면 백업으로 되돌리고 멈춤 → reload.
# 키는 /etc/nginx/conf.d/stock-research-data-key.conf(root 600)에만 있다. 저장소에 넣지 않는다.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "sudo 로 실행한다"; exit 1; }
cd "$(dirname "$0")/.."

install -d -o ubuntu -g ubuntu -m 755 /srv/stock-data /srv/stock-data/bundles /srv/stock-data/incoming

KEYCONF=/etc/nginx/conf.d/stock-research-data-key.conf
# map_hash_bucket_size: 48자 키는 기본 칸(64)에 안 들어가 nginx -t 가 실패한다(10-30 실측). 키 파일 안에 같이 둔다.
write_keyconf() {
    umask 077
    printf 'map_hash_bucket_size 128;\nmap $http_x_data_key $research_data_ok {\n    default 0;\n    "%s" 1;\n}\n' "$1" > "$KEYCONF"
    chmod 600 "$KEYCONF"
}
NEWKEY=0
if [ -f "$KEYCONF" ]; then
    KEY=$(grep -o '[0-9a-f]\{48\}' "$KEYCONF")
    write_keyconf "$KEY"          # 옛 형식(칸 크기 없음) 고치기 — 키는 그대로
    echo "키 파일이 이미 있다 — 키는 그대로 둔다"
else
    NEWKEY=1
    KEY=$(openssl rand -hex 24)
    write_keyconf "$KEY"
    echo "=================================================================="
    echo " 새 키(RESEARCH_DATA_KEY) — 이 화면에서만 보인다. Claude 에게 보내지 않는다."
    echo "   $KEY"
    echo " 넣을 곳 두 군데: PC .env 에 RESEARCH_DATA_KEY=키  ·  claude.ai/code 환경 설정의 환경 변수"
    echo " 다시 보려면: sudo grep -o '[0-9a-f]\{48\}' $KEYCONF"
    echo "=================================================================="
fi

SITE=$(readlink -f /etc/nginx/sites-enabled/wonithink-stock.conf)
RL=/etc/nginx/conf.d/stock-ratelimit.conf
STAMP=$(date +%Y%m%d-%H%M%S)
cp "$SITE" "$SITE.bak-research-data-$STAMP"
cp "$RL" "/etc/nginx/stock-ratelimit.conf.bak-research-data-$STAMP"    # conf.d 안에 두면 같이 읽혀 zone 이 겹친다
cp deploy/nginx-wonithink-stock.conf "$SITE"
cp deploy/nginx-stock-ratelimit.conf "$RL"
if ! nginx -t; then
    cp "$SITE.bak-research-data-$STAMP" "$SITE"
    cp "/etc/nginx/stock-ratelimit.conf.bak-research-data-$STAMP" "$RL"
    [ "$NEWKEY" = 1 ] && rm -f "$KEYCONF"     # 새로 만든 키 파일이 conf.d 에 남으면 다음 reload·재부팅에서 nginx 가 안 뜬다
    nginx -t || echo "★ 되돌린 뒤에도 nginx -t 실패 — $KEYCONF 를 확인한다(재부팅·reload 전에)"
    echo "nginx -t 실패 — 백업으로 되돌렸다(reload 안 함)"
    exit 1
fi
systemctl reload nginx
echo "완료: https://wonithink-stock.duckdns.org/research-data/ (키 없으면 401)"
