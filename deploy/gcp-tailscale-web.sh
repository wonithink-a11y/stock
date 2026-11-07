#!/bin/bash
# GCP 임시 서버에 autotrader 웹을 Tailscale **사설** 주소로 올린다(공개 인터넷에 안 열림, DuckDNS·nginx·certbot 불필요).
# 사용자의 Tailscale 에 로그인한 기기(폰·PC)에서만 https://stock-gcp.<tailnet>.ts.net/autotrader/ 로 열린다.
# 안 하는 일: 증권사 키 넣기 · 로그인 설정(web-setup) · 법령 서버(별도).
#
#   curl -fsSL https://raw.githubusercontent.com/wonithink-a11y/stock/ccr-c32c9d34-v87x7r/deploy/gcp-tailscale-web.sh -o t.sh && bash t.sh
set -euo pipefail
U=/home/ubuntu

command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
if ! tailscale status >/dev/null 2>&1; then
    echo "== 아래에 나오는 주소(https://login.tailscale.com/...)를 브라우저에서 열고 로그인하세요"
    sudo tailscale up --hostname=stock-gcp
fi

echo "== autotrader 설정·상태 폴더"
sudo -u ubuntu bash -c "cd $U/collector && git pull -q --ff-only || true
mkdir -p $U/collector-venv/autotrader/state $U/collector-venv/logs
[ -f $U/collector-venv/autotrader/autotrader.local.json ] || {
  cp autotrader/config.example.json $U/collector-venv/autotrader/autotrader.local.json
  sed -i 's#\"state_dir\": \"autotrader/state\"#\"state_dir\": \"$U/collector-venv/autotrader/state\"#' $U/collector-venv/autotrader/autotrader.local.json; }
[ -f autotrader/targets.local.json ] || cp autotrader/targets.example.json autotrader/targets.local.json"

echo "== 웹 유닛"
sudo cp $U/collector/deploy/autotrader-web.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now autotrader-web
sleep 2; systemctl is-active autotrader-web

echo "== Tailscale serve (사설: tailnet 안에서만)"
sudo tailscale serve --bg --https=443 --set-path /autotrader http://127.0.0.1:8787/autotrader
tailscale serve status
echo "완료 — 폰에도 Tailscale 앱을 깔고 같은 계정으로 로그인한 뒤 위 주소 + /autotrader/ 를 연다. 다음: web-setup(비밀번호·인증앱)"
