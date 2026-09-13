"""engine/live/bithumbClient.py 구조 테스트 - 네트워크 없음. JWT 페이로드
구성이 빗썸 공식 스펙(payload access_key/nonce/timestamp/query_hash?/
query_hash_alg?, HS256 서명, apidocs.bithumb.com 2026-09-14 확인)과
일치하는지만 본다 - 실제 HTTP 호출은 probe-bithumb-*-smoke.py가 담당한다."""
import hashlib
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt as pyjwt

from engine.live.bithumbClient import BithumbClient, BithumbError, _query_string

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def _client():
    c = BithumbClient()
    c.access_key = "test-access-key"
    c.secret_key = "test-secret-key"
    return c


def test_no_query_payload_has_no_hash():
    c = _client()
    headers = c._auth_headers()
    token = headers["Authorization"].split(" ", 1)[1]
    payload = pyjwt.decode(token, c.secret_key, algorithms=["HS256"])
    ok("access_key present", payload.get("access_key") == "test-access-key", payload)
    ok("nonce is a valid uuid", bool(uuid.UUID(payload.get("nonce", ""))), payload)
    ok("timestamp is present and ms-scale", isinstance(payload.get("timestamp"), int)
       and payload["timestamp"] > 10**12, payload)
    ok("no query_hash when no query given", "query_hash" not in payload, payload)


def test_query_payload_hash_matches_spec():
    c = _client()
    query = {"market": "KRW-BTC", "side": "bid", "order_type": "limit", "price": "80000000", "volume": "0.001"}
    headers = c._auth_headers(query)
    token = headers["Authorization"].split(" ", 1)[1]
    payload = pyjwt.decode(token, c.secret_key, algorithms=["HS256"])
    expected_qs = _query_string(query).encode("utf-8")
    expected_hash = hashlib.sha512(expected_qs).hexdigest()
    ok("query_hash matches SHA512(simple key=value join, 빗썸 예제 그대로)",
       payload.get("query_hash") == expected_hash, payload)
    ok("query_hash_alg is SHA512", payload.get("query_hash_alg") == "SHA512", payload)


def test_query_string_is_simple_join_not_urlencoded():
    # 공식 예제: "market=KRW-BTC&side=bid&order_type=limit&price=80000000&volume=0.001"
    query = {"market": "KRW-BTC", "side": "bid", "order_type": "limit",
              "price": "80000000", "volume": "0.001"}
    qs = _query_string(query)
    ok("query string matches official example exactly",
       qs == "market=KRW-BTC&side=bid&order_type=limit&price=80000000&volume=0.001", qs)


def test_missing_keys_raise_on_auth_call():
    c = BithumbClient()
    c.access_key = ""
    c.secret_key = ""
    try:
        c._auth_headers()
        ok("raises BithumbError when keys missing", False)
    except BithumbError:
        ok("raises BithumbError when keys missing", True)


def test_public_client_needs_no_keys():
    # __init__ must not raise even with no .env / no keys - paper trading
    # depends on this (BithumbPaperBroker only ever calls public methods).
    try:
        BithumbClient()
        ok("BithumbClient() succeeds without keys", True)
    except Exception as e:
        ok("BithumbClient() succeeds without keys", False, str(e))


def test_side_validation():
    c = _client()
    try:
        c.place_order("KRW-BTC", side="buy", order_type="limit", price=10000, volume=0.001)
        ok("place_order rejects invalid side", False)
    except ValueError:
        ok("place_order rejects invalid side", True)


def main():
    test_no_query_payload_has_no_hash()
    test_query_payload_hash_matches_spec()
    test_query_string_is_simple_join_not_urlencoded()
    test_missing_keys_raise_on_auth_call()
    test_public_client_needs_no_keys()
    test_side_validation()
    print(f"\n{'='*40}\npassed {passed} . failed {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
