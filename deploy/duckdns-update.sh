#!/bin/bash
# duckdns-update.sh — stock-new(오라클) 공인 IP가 바뀌면 DuckDNS 레코드도 갱신.
# ip= 파라미터를 비워서 보내면 DuckDNS가 요청을 보낸 쪽의 IP를 그대로 쓴다
# (공식 권장 방식 - 우리가 직접 "지금 내 IP가 뭔지" 알아낼 필요가 없다).
# 이미 같은 IP면 DuckDNS 쪽에서도 그냥 OK를 준다(멱등) - 매일 돌려도 안전.
set -euo pipefail

ENV_FILE="$(dirname "$0")/.env"
if [ -f "$ENV_FILE" ]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
fi

if [ -z "${DUCKDNS_DOMAIN:-}" ] || [ -z "${DUCKDNS_TOKEN:-}" ]; then
  echo "DUCKDNS_DOMAIN/DUCKDNS_TOKEN이 없다 - $ENV_FILE 확인" >&2
  exit 1
fi

RESPONSE=$(curl -fsS "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip=")
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) duckdns update -> ${RESPONSE}"

if [ "$RESPONSE" != "OK" ]; then
  echo "DuckDNS 갱신 실패 (응답: ${RESPONSE})" >&2
  exit 1
fi
