#!/bin/bash
# 서버 상태 백업을 tgz 로 stdout 에 낸다 — PC 의 scripts/pull-gcp-backup.ps1 이 ssh 로 받아 간다.
# authorized_keys 에 command="...이 파일",restrict 로 묶어 그 키는 이것만 실행할 수 있다(셸·터널 불가).
# 포함: ~/collector-venv(프로필·상태·가격 목표·카카오 토큰·모의 원장 …) + ~/collector/data/paper
# 제외: .env(키 — PC .env 가 정본) · 파이썬 실행부(bin/lib…) · 로그 · 토큰 캐시. 민감(웹 인증 해시·카카오 토큰) — PC 디스크에만 둔다.
cd /home/ubuntu || exit 1
exec tar czf - --ignore-failed-read --warning=no-file-changed \
  --exclude='collector-venv/bin' --exclude='collector-venv/lib' --exclude='collector-venv/lib64' \
  --exclude='collector-venv/include' --exclude='collector-venv/share' --exclude='collector-venv/logs' \
  --exclude='collector-venv/.env*' --exclude='*/tokens' --exclude='*.pyc' \
  collector-venv collector/data/paper 2>/dev/null
