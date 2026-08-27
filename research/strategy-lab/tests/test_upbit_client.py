"""engine/live/upbitClient.py 구조 테스트 - 네트워크 없음. JWT 페이로드
구성이 업비트 공식 스펙(payload access_key/nonce/query_hash?/query_hash_alg?,
HS512 서명, docs.upbit.com 2026-08-27 확인)과 일치하는지만 본다 - 실제
HTTP 호출은 probe-upbit-*-smoke.py가 담당한다."""
import hashlib
import os
import sys
import uuid
from urllib.parse import unquote, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jwt as pyjwt

from engine.live.upbitClient import UpbitClient, UpbitError

passed, failed = 0, 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def _client():
    c = UpbitClient()
    c.access_key = "test-access-key"
    c.secret_key = "test-secret-key"
    return c


def test_no_query_payload_has_no_hash():
    c = _client()
    headers = c._auth_headers()
    token = headers["Authorization"].split(" ", 1)[1]
    payload = pyjwt.decode(token, c.secret_key, algorithms=["HS512"])
    ok("access_key present", payload.get("access_key") == "test-access-key", payload)
    ok("nonce is a valid uuid", bool(uuid.UUID(payload.get("nonce", ""))), payload)
    ok("no query_hash when no query given", "query_hash" not in payload, payload)


def test_query_payload_hash_matches_spec():
    c = _client()
    query = {"market": "KRW-BTC", "side": "bid", "ord_type": "price", "price": "10000"}
    headers = c._auth_headers(query)
    token = headers["Authorization"].split(" ", 1)[1]
    payload = pyjwt.decode(token, c.secret_key, algorithms=["HS512"])
    expected_qs = unquote(urlencode(query, doseq=True)).encode("utf-8")
    expected_hash = hashlib.sha512(expected_qs).hexdigest()
    ok("query_hash matches SHA512(unquoted urlencoded query)",
       payload.get("query_hash") == expected_hash, payload)
    ok("query_hash_alg is SHA512", payload.get("query_hash_alg") == "SHA512", payload)


def test_missing_keys_raise_on_auth_call():
    c = UpbitClient()
    c.access_key = ""
    c.secret_key = ""
    try:
        c._auth_headers()
        ok("raises UpbitError when keys missing", False)
    except UpbitError:
        ok("raises UpbitError when keys missing", True)


def test_public_client_needs_no_keys():
    # __init__ must not raise even with no .env / no keys - paper trading
    # depends on this (UpbitPaperBroker only ever calls public methods).
    try:
        UpbitClient()
        ok("UpbitClient() succeeds without keys", True)
    except Exception as e:
        ok("UpbitClient() succeeds without keys", False, str(e))


def test_side_validation():
    c = _client()
    try:
        c.place_order("KRW-BTC", side="buy", ord_type="price", price=10000)
        ok("place_order rejects invalid side", False)
    except ValueError:
        ok("place_order rejects invalid side", True)


def main():
    test_no_query_payload_has_no_hash()
    test_query_payload_hash_matches_spec()
    test_missing_keys_raise_on_auth_call()
    test_public_client_needs_no_keys()
    test_side_validation()
    print(f"\n{'='*40}\npassed {passed} . failed {failed}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
