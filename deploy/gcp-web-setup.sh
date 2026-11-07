#!/bin/bash
# GCP 임시 서버에 autotrader 웹(wonithink-stock.duckdns.org/autotrader/)만 살리는 스크립트 — 세션인수인계-2026-11-07.md.
# 하는 일(멱등): nginx+certbot 설치 · /autotrader/ 길 하나 · 웹 유닛 · (선택) DuckDNS IP 갱신 · 인증서.
# 안 하는 일: 증권사 키(.env) 넣기 · 다른 8766 계열 길(/pins 등 — GCP 엔 그 서버가 없다) · 로그인 설정(web-setup).
#
# 실행(기본 계정 wonithink 로, GCP 브라우저 SSH):
#   curl -fsSL https://raw.githubusercontent.com/wonithink-a11y/stock/ccr-c32c9d34-v87x7r/deploy/gcp-web-setup.sh -o w.sh
#   DUCKDNS_TOKEN=<토큰> bash w.sh        # 토큰은 이 한 번 환경변수로만 쓰고 파일에 안 남긴다. 없으면 duckdns.org 에서 IP 를 손으로 바꾼다.
set -euo pipefail
DOMAIN=wonithink-stock.duckdns.org
SUB=${DOMAIN%%.*}
BR=ccr-c32c9d34-v87x7r
RAW=https://raw.githubusercontent.com/wonithink-a11y/stock/$BR/deploy
U=/home/ubuntu

MYIP=$(curl -fsS https://api.ipify.org)
echo "== 이 서버 공인 IP: $MYIP"
if [ -n "${DUCKDNS_TOKEN:-}" ]; then
    echo "== DuckDNS 갱신 -> $(curl -fsS "https://www.duckdns.org/update?domains=$SUB&token=$DUCKDNS_TOKEN&ip=$MYIP")"
fi

echo "== 패키지"
sudo apt-get update -qq
sudo apt-get install -y -qq nginx certbot python3-certbot-nginx

echo "== autotrader 설정·상태 폴더"
sudo -u ubuntu bash -c "cd $U/collector && git pull -q --ff-only || true
mkdir -p $U/collector-venv/autotrader/state $U/collector-venv/logs
[ -f $U/collector-venv/autotrader/autotrader.local.json ] || {
  cp autotrader/config.example.json $U/collector-venv/autotrader/autotrader.local.json
  sed -i 's#\"state_dir\": \"autotrader/state\"#\"state_dir\": \"$U/collector-venv/autotrader/state\"#' $U/collector-venv/autotrader/autotrader.local.json; }
[ -f autotrader/targets.local.json ] || cp autotrader/targets.example.json autotrader/targets.local.json"

echo "== nginx (80 에서 /autotrader/ 만. TLS 는 certbot 이 붙인다)"
sudo curl -fsSL $RAW/nginx-stock-ratelimit.conf -o /etc/nginx/conf.d/stock-ratelimit.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo tee /etc/nginx/sites-enabled/wonithink-stock.conf >/dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    server_tokens off;
    limit_req_status 429;
    location = /autotrader { return 301 /autotrader/; }
    location /autotrader/ {
        limit_req zone=autotrader_web burst=30 nodelay;
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 15s;
    }
    location / { return 404; }
}
EOF
sudo nginx -t && sudo systemctl reload nginx

echo "== 웹 유닛"
sudo cp $U/collector/deploy/autotrader-web.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now autotrader-web
sleep 2; systemctl is-active autotrader-web

echo "== DNS 확인"
RES=$(getent hosts $DOMAIN | cut -d' ' -f1 || true)
if [ "$RES" != "$MYIP" ]; then
    echo "!! $DOMAIN 이 $RES 를 가리킨다(이 서버는 $MYIP). duckdns.org 에서 IP 를 $MYIP 로 바꾼 뒤 이 스크립트를 다시 실행."
    exit 1
fi
echo "== 인증서 (HTTPS 리다이렉트 포함)"
sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --register-unsafely-without-email --redirect
echo "완료: https://$DOMAIN/autotrader/  — 다음: 로그인 설정(web-setup)"
