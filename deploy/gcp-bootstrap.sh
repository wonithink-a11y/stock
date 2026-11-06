#!/bin/bash
# GCP e2-micro(Ubuntu 24.04, 1GB) 임시 서버 첫 설정 — 세션인수인계-2026-11-06.md §2-1.
# OCI 정지(11-07) 대체. 유닛 파일이 /home/ubuntu 를 하드코딩하므로 `ubuntu` 사용자를 만든다.
#
# 기본 계정(구글 계정명)으로 접속한 뒤 한 줄:
#   curl -fsSL https://raw.githubusercontent.com/wonithink-a11y/stock/main/deploy/gcp-bootstrap.sh | bash
#   (이 브랜치가 main 에 병합되기 전이면 브랜치 이름으로 raw 주소를 바꾼다)
#
# 하는 일(멱등): 시간대 KST · 스왑 2GB · 패키지 · ubuntu 사용자(+ssh 키 복사) · 저장소 clone · venv.
# 안 하는 일: 키(.env) 입력 · 유닛 설치 · nginx · duckdns. 유닛은 .env 를 넣은 뒤 install-unit.sh 로 하나씩.
set -euo pipefail
[ "$(id -u)" -ne 0 ] || { echo "root 말고 기본 계정으로 실행(sudo 는 안에서 쓴다)"; exit 2; }
REPO_URL="https://github.com/wonithink-a11y/stock.git"

echo "== 시간대 KST (타이머 9시간 밀림 방지 — 08-30 실측)"
sudo timedatectl set-timezone Asia/Seoul

echo "== 스왑 2GB"
if ! swapon --show | grep -q /swapfile; then
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "== 패키지 (node 는 20 이상 필요 — apt 기본은 18)"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv python3-pip curl ca-certificates
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y -qq nodejs
fi

echo "== ubuntu 사용자 (유닛 경로 /home/ubuntu 유지)"
if ! id ubuntu >/dev/null 2>&1; then
    sudo useradd -m -s /bin/bash ubuntu
fi
echo 'ubuntu ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/90-ubuntu >/dev/null
sudo chmod 440 /etc/sudoers.d/90-ubuntu
sudo install -d -m 700 -o ubuntu -g ubuntu /home/ubuntu/.ssh
if [ -f "$HOME/.ssh/authorized_keys" ]; then       # 지금 로그인한 키를 그대로 허용
    sudo install -m 600 -o ubuntu -g ubuntu "$HOME/.ssh/authorized_keys" /home/ubuntu/.ssh/authorized_keys
fi

echo "== 저장소 · venv (ubuntu 로)"
sudo -u ubuntu -H bash -s "$REPO_URL" <<'EOS'
set -euo pipefail
[ -d ~/collector/.git ] || git clone -q "$1" ~/collector
[ -d ~/collector-venv ] || python3 -m venv ~/collector-venv
mkdir -p ~/collector-venv/logs
~/collector-venv/bin/pip install -q --upgrade pip "setuptools<81"
# ponytail: 알림·모의 슬리브에 필요한 최소 묶음. 유닛이 ImportError 를 내면 그 패키지만 더한다.
~/collector-venv/bin/pip install -q pandas numpy requests lxml html5lib pyarrow
EOS

cat <<'MSG'

== 끝. 다음 (ubuntu 로 접속: ssh ubuntu@<새 IP>)
1. 키 입력:  ~/collector-venv/.env  (scripts/setup-keys-interactive.py 방식 — 값은 대화에 붙이지 않는다)
   최소: TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID · TELEGRAM_ALERT_CHAT_ID(·TRADE/URGENT/NEWS/REPORT/SCORE)
2. 유닛(우선순위 순, 하나씩):
   # 실패 알림 유닛(install-unit.sh 는 '@' 이름을 거부하므로 수동):
   sudo cp ~/collector/deploy/unit-failure-notify@.service /etc/systemd/system/ && sudo systemctl daemon-reload
   # collector-pull 은 @USER@ 자리표시자가 있어 치환해서 설치(install-unit.sh 불가):
   for f in service timer; do sed -e "s|@REPO@|$HOME/collector|g" -e "s|@USER@|ubuntu|g" -e "s|@LOGDIR@|$HOME/collector-venv/logs|g" ~/collector/deploy/collector-pull.$f | sudo tee /etc/systemd/system/collector-pull.$f >/dev/null; done
   sudo systemctl daemon-reload && sudo systemctl enable --now collector-pull.timer
   bash ~/collector/deploy/install-unit.sh vm-status-snapshot
3. 확인: free -h · swapon --show · timedatectl · systemctl list-timers
MSG
