"""Bithumb REST client - 인증(공개 시세는 불필요)·주문·잔고조회.

upbitClient.py와 같은 모양(단일 _request() 관문 + 모듈 레벨 RateLimiter +
.env 키 로딩 + "공개 메서드는 키 없이도 100% 동작")이지만 스펙이 다르다
(apidocs.bithumb.com "빠른 시작 가이드"·"인증 토큰 생성하기"·"API 호출해
보기" 직접 확인, 2026-09-14):

  - JWT 서명이 **HS256**이다(업비트는 HS512 - 그대로 베끼면 인증이 깨진다).
  - payload에 `nonce` 외에 **timestamp**(ms, 항상 포함)가 추가로 필요하다.
  - query_hash용 쿼리 문자열은 업비트처럼 urlencode+unquote가 아니라
    **단순 "key=value&key2=value2" 조인**이다(빗썸 공식 예제 그대로).
  - 주문 생성/취소가 **/v2/orders·/v2/order**(v2)고, 시세·잔고·주문가능
    조회는 **/v1/...**다 - 버전이 엔드포인트마다 다르다(빗썸 자체 설계,
    실수하기 쉬운 지점).
  - 필드명이 업비트와 다르다: `ord_type`이 아니라 **order_type**,
    주문 식별자가 `uuid`가 아니라 **order_id**.

엔드포인트·파라미터는 공식 문서 예제 그대로다:
    공개 시세   GET /v1/ticker?markets=...        (인증 불필요)
    공개 호가   GET /v1/orderbook?markets=...      (인증 불필요)
    공개 페어   GET /v1/market/all                 (인증 불필요)
    잔고        GET /v1/accounts                   (JWT, 파라미터 없음)
    주문가능    GET /v1/orders/chance?market=...   (JWT, query_hash)
    주문 생성   POST /v2/orders {market,side,order_type,price,volume} (JWT, query_hash)
    주문 취소   DELETE /v2/order?order_id=...       (JWT, query_hash)

★ 개별 주문 상태 조회(체결 확인) 엔드포인트는 이 세션이 확인한 3개 문서
페이지 어디에도 명시적으로 없었다 - GET /v1/order?order_id=... 로
추정만 했다(주문취소가 같은 /v2/order 경로에 order_id 파라미터를 쓰는 것과
업비트의 GET /v1/order?uuid=... 패턴에 근거한 유추, **미검증**). 이 값은
BithumbBroker.check_fill()(dormant, 아래 참고)에서만 쓰이고
BithumbPaperBroker는 이 엔드포인트를 전혀 안 부른다 - 페이퍼 매매는
이 불확실성과 무관하게 안전하다.
"""
import hashlib
import os
import threading
import time
import uuid
from pathlib import Path

import jwt
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
BASE_URL = "https://api.bithumb.com"
PATH_ORDERS = "/v2/orders"
PATH_ORDER = "/v2/order"
PATH_ORDER_CHANCE = "/v1/orders/chance"
PATH_ACCOUNTS = "/v1/accounts"
PATH_TICKER = "/v1/ticker"
PATH_ORDERBOOK = "/v1/orderbook"
PATH_MARKET_ALL = "/v1/market/all"


class _RateLimiter:
    """공개 초당 150회·비공개 초당 140회(문서 확인, 2026-09-14) - 더 낮은
    쪽으로 보수적으로 묶는다. upbitClient.py의 _RateLimiter와 동일한
    모듈 레벨 싱글턴 + 락 설계(교훈72)."""
    def __init__(self, min_interval_sec=0.008):  # 140회/초에 ~10% 여유
        self.min_interval_sec = min_interval_sec
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            if sleep_for > 0:
                time.sleep(sleep_for)
                now = time.monotonic()
            self._next_allowed = now + self.min_interval_sec


_RATE_LIMITER = _RateLimiter()


class BithumbError(RuntimeError):
    pass


def _request(method, url, **kwargs):
    _RATE_LIMITER.wait()
    return requests.request(method, url, **kwargs)


def _load_env():
    env = {}
    p = REPO_ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    for k in ("BITHUMB_ACCESS_KEY", "BITHUMB_SECRET_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _query_string(query: dict) -> str:
    """빗썸 공식 예제 그대로 - urlencode가 아니라 단순 join.
    (인증 토큰 생성하기 문서의 JS 예제: query.map(([k,v])=>`${k}=${v}`).join('&'))"""
    return "&".join(f"{k}={v}" for k, v in query.items())


class BithumbClient:
    def __init__(self):
        env = _load_env()
        self.access_key = env.get("BITHUMB_ACCESS_KEY", "")
        self.secret_key = env.get("BITHUMB_SECRET_KEY", "")
        # 키가 없어도 생성은 성공한다 - 공개 메서드만 쓰는
        # BithumbPaperBroker가 이걸 요구한다.

    def _require_keys(self):
        if not (self.access_key and self.secret_key):
            raise BithumbError(
                "BITHUMB_ACCESS_KEY/BITHUMB_SECRET_KEY 중 하나가 .env에 없다. "
                "scripts/setup-keys-interactive.py 를 먼저 실행한다.")

    def _auth_headers(self, query: dict = None):
        self._require_keys()
        payload = {
            "access_key": self.access_key,
            "nonce": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
        }
        if query:
            query_string = _query_string(query).encode("utf-8")
            payload["query_hash"] = hashlib.sha512(query_string).hexdigest()
            payload["query_hash_alg"] = "SHA512"
        token = jwt.encode(payload, self.secret_key, algorithm="HS256")
        if isinstance(token, bytes):  # PyJWT<2.0 returns bytes, >=2.0 returns str
            token = token.decode("utf-8")
        return {"Authorization": "Bearer " + token}

    @staticmethod
    def _raise_if_error(r, body, context):
        if r.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            raise BithumbError(f"{context}: {body}")

    # ---- 공개 (키 불필요) ----

    def get_ticker(self, market):
        r = _request("GET", BASE_URL + PATH_TICKER, params={"markets": market}, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"시세 조회 실패({market})")
        if not body:
            raise BithumbError(f"시세 조회 실패({market}): 빈 응답")
        return float(body[0]["trade_price"])

    def get_orderbook(self, market):
        """반환: 빗썸 응답 그대로(list[dict], orderbook_units 포함)."""
        r = _request("GET", BASE_URL + PATH_ORDERBOOK, params={"markets": market}, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"호가 조회 실패({market})")
        if not body:
            raise BithumbError(f"호가 조회 실패({market}): 빈 응답")
        return body[0]

    def get_market_all(self):
        r = _request("GET", BASE_URL + PATH_MARKET_ALL, params={"isDetails": "false"}, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, "거래대상 목록 조회 실패")
        return body

    # ---- 인증 필요 ----

    def get_accounts(self):
        headers = self._auth_headers()
        r = _request("GET", BASE_URL + PATH_ACCOUNTS, headers=headers, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, "잔고 조회 실패")
        return body

    def get_order_chance(self, market):
        query = {"market": market}
        headers = self._auth_headers(query)
        r = _request("GET", BASE_URL + PATH_ORDER_CHANCE, headers=headers, params=query, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"주문가능정보 조회 실패({market})")
        return body

    def place_order(self, market, side, order_type, volume=None, price=None):
        """side: 'bid'(매수) | 'ask'(매도). order_type: 'limit'|'price'|'market'|'best'
        (limit만 공식 예제로 확인됨 - price/market/best는 업비트와 동일한
        시장가 비대칭 관례로 유추, **미검증**). 반환: 빗썸 응답 dict(order_id 포함)."""
        if side not in ("bid", "ask"):
            raise ValueError("side must be bid or ask")
        body_params = {"market": market, "side": side, "order_type": order_type}
        if volume is not None:
            body_params["volume"] = str(volume)
        if price is not None:
            body_params["price"] = str(price)
        headers = self._auth_headers(body_params)
        headers["Content-Type"] = "application/json; charset=utf-8"
        r = _request("POST", BASE_URL + PATH_ORDERS, headers=headers, json=body_params, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"주문 실패({side} {market})")
        return body

    def cancel_order(self, order_id):
        query = {"order_id": order_id}
        headers = self._auth_headers(query)
        r = _request("DELETE", BASE_URL + PATH_ORDER, headers=headers, params=query, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"주문취소 실패({order_id})")
        return body

    def get_order(self, order_id):
        """★ 미검증 엔드포인트(파일 docstring 참고) - BithumbBroker.check_fill()
        에서만 쓰인다. 실사용 전 apidocs.bithumb.com API 레퍼런스에서
        정확한 경로를 재확인한다."""
        query = {"order_id": order_id}
        headers = self._auth_headers(query)
        r = _request("GET", BASE_URL + PATH_ORDER, headers=headers, params=query, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"주문조회 실패({order_id})")
        return body
