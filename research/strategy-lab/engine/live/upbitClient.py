"""Upbit REST client - 인증(공개 시세는 불필요)·주문·잔고조회.

kisVtsClient.py와 같은 모양(단일 _request() 관문 + 모듈 레벨 RateLimiter +
.env 키 로딩)이지만 두 가지가 다르다:
  - 인증이 OAuth 토큰 발급이 아니라 매 요청 자체서명 JWT다 - 캐시할 서버발급
    토큰이 없다(매번 새 nonce로 새로 만든다).
  - 도메인이 하나뿐이다(api.upbit.com) - KIS처럼 "라이브 키 이름 자체를
    모르게" 격리할 방법이 없다. 그래서 이 클라이언트는 키 없이도 생성
    가능하게 만든다 - 공개 메서드(get_ticker/get_candles_days)는 키를
    절대 요구하지 않고, 인증 메서드(get_accounts/place_order/get_order)만
    호출 시점에 키 존재를 검사한다. UpbitPaperBroker는 공개 메서드만
    쓰므로 키가 아예 없어도 모의매매가 100% 동작한다.

엔드포인트·파라미터·JWT 구성은 업비트 공식 문서(docs.upbit.com, 2026-08-27
확인) 그대로다:
    인증   JWT payload {access_key, nonce, query_hash?, query_hash_alg?},
           HS512 서명(비밀키는 base64 디코딩 없이 원문 그대로 사용),
           Authorization: Bearer <token>. query_hash는 쿼리(GET) 또는
           바디(POST)를 "URL 인코딩 되지 않은" 문자열로 SHA512 - 공식
           예제 관례대로 urlencode(doseq=True) 후 unquote()로 만든다.
    주문   POST /v1/orders (side bid/ask, ord_type limit/price/market/best -
           시장가 매수는 ord_type=price+price(총액), 시장가 매도는
           ord_type=market+volume(수량) - 업비트 자체가 비대칭이다)
    조회   GET  /v1/order?uuid=...  (state wait/watch/done/cancel,
           executed_volume, trades[] {price,volume})
    잔고   GET  /v1/accounts  (currency/balance/locked)
    시세   GET  /v1/ticker?markets=...  (공개, 인증 불필요, trade_price)
    캔들   GET  /v1/candles/days?market=...&count=...  (공개, 인증 불필요,
           초당 최대 10회 - 문서 명시)
"""
import hashlib
import os
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import unquote, urlencode

import jwt
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
BASE_URL = "https://api.upbit.com"
PATH_ORDERS = "/v1/orders"
PATH_ORDER = "/v1/order"
PATH_ACCOUNTS = "/v1/accounts"
PATH_TICKER = "/v1/ticker"
PATH_CANDLES_DAYS = "/v1/candles/days"


class _RateLimiter:
    """공개 엔드포인트 초당 10회(문서 확인, 2026-08-27) - 인증 엔드포인트도
    같은 값으로 보수적으로 묶는다. 실거래 전에는 주문 계열 엔드포인트의
    실제 한도(문서상 그룹별로 다를 수 있음)를 별도로 재확인한다 - 이
    세션은 공개 한도만 확인했다. kisVtsClient.py의 _RateLimiter와 동일한
    모듈 레벨 싱글턴 + 락 설계(교훈72 - 호출부마다 규율을 요구하지 않는다)."""
    def __init__(self, min_interval_sec=0.11):  # 10회/초에 ~10% 여유
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


class UpbitError(RuntimeError):
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
    for k in ("UPBIT_ACCESS_KEY", "UPBIT_SECRET_KEY"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


class UpbitClient:
    def __init__(self):
        env = _load_env()
        self.access_key = env.get("UPBIT_ACCESS_KEY", "")
        self.secret_key = env.get("UPBIT_SECRET_KEY", "")
        # 키가 없어도 생성은 성공한다 - 공개 메서드만 쓰는 UpbitPaperBroker가
        # 이걸 요구한다. 인증 메서드를 실제로 부를 때만 _require_keys()가 검사.

    def _require_keys(self):
        if not (self.access_key and self.secret_key):
            raise UpbitError(
                "UPBIT_ACCESS_KEY/UPBIT_SECRET_KEY 중 하나가 .env에 없다. "
                "scripts/setup-upbit-key.py 를 먼저 실행한다.")

    def _auth_headers(self, query=None):
        self._require_keys()
        payload = {"access_key": self.access_key, "nonce": str(uuid.uuid4())}
        if query:
            query_string = unquote(urlencode(query, doseq=True)).encode("utf-8")
            payload["query_hash"] = hashlib.sha512(query_string).hexdigest()
            payload["query_hash_alg"] = "SHA512"
        token = jwt.encode(payload, self.secret_key, algorithm="HS512")
        if isinstance(token, bytes):  # PyJWT<2.0 returns bytes, >=2.0 returns str
            token = token.decode("utf-8")
        return {"Authorization": "Bearer " + token}

    @staticmethod
    def _raise_if_error(r, body, context):
        if r.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            raise UpbitError(f"{context}: {body}")

    # ---- 공개 (키 불필요) ----

    def get_ticker(self, market):
        r = _request("GET", BASE_URL + PATH_TICKER, params={"markets": market}, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"시세 조회 실패({market})")
        if not body:
            raise UpbitError(f"시세 조회 실패({market}): 빈 응답")
        return float(body[0]["trade_price"])

    def get_candles_days(self, market, count=200, to=None):
        """반환: 업비트 응답 그대로(list[dict], 최신순) - DataFrame 변환은
        engine/live/upbitCandles.py 몫이다(이 클래스는 순수 HTTP 래핑만)."""
        params = {"market": market, "count": count}
        if to:
            params["to"] = to
        r = _request("GET", BASE_URL + PATH_CANDLES_DAYS, params=params, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"캔들 조회 실패({market})")
        return body

    # ---- 인증 필요 ----

    def get_accounts(self):
        headers = self._auth_headers()
        r = _request("GET", BASE_URL + PATH_ACCOUNTS, headers=headers, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, "잔고 조회 실패")
        return body

    def place_order(self, market, side, ord_type, volume=None, price=None):
        """side: 'bid'(매수) | 'ask'(매도). ord_type: 'limit'|'price'|'market'|'best'.
        시장가 매수(price)는 volume 생략, 시장가 매도(market)는 price 생략 -
        업비트 자체 비대칭(문서 확인). 반환: 업비트 응답 dict(uuid 포함)."""
        if side not in ("bid", "ask"):
            raise ValueError("side must be bid or ask")
        query = {"market": market, "side": side, "ord_type": ord_type}
        if volume is not None:
            query["volume"] = str(volume)
        if price is not None:
            query["price"] = str(price)
        headers = self._auth_headers(query)
        r = _request("POST", BASE_URL + PATH_ORDERS, headers=headers, json=query, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"주문 실패({side} {market})")
        return body

    def get_order(self, order_uuid):
        query = {"uuid": order_uuid}
        headers = self._auth_headers(query)
        r = _request("GET", BASE_URL + PATH_ORDER, headers=headers, params=query, timeout=10)
        body = r.json()
        self._raise_if_error(r, body, f"주문조회 실패({order_uuid})")
        return body
