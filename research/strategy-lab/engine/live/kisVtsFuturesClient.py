"""KIS 모의투자(VTS) 국내선물옵션 REST 클라이언트 - 인증·잔고·주문.

`kisVtsClient.py`(국내주식)·`kisVtsOverseasClient.py`(해외주식)와 같은
자리에 두는 세 번째 상품 클라이언트다. 계좌·앱키가 완전히 별도라서
합치지 않는다(주식 VTS 계좌와 선물 VTS 계좌는 KIS가 아예 다른 계좌로
발급한다 - 계좌상품코드가 "01"이 아니라 "03").

라이브 도메인은 이 파일 어디에도 등장하지 않는다(BASE_URL 상수 하나뿐,
항상 VTS). KIS_VTS_FUTURES_APP_KEY/APP_SECRET/ACCOUNT_NO만 읽는다.

★ 이 파일의 TR_ID·필드명은 2026-09-13에 KIS 공식 예제
(github.com/koreainvestment/open-trading-api,
examples_user/domestic_futureoption/domestic_futureoption_functions.py)
에서 직접 확인해 옮겼다 - 주식 클라이언트와 같은 수준의 출처 검증을
거쳤다. 단 **실제 계좌로 호출을 확인한 적은 아직 없다**(계좌 자체가
없다, 2026-09-13 기준) - 그래서 order()는 기본값이 지정가이고, 첫
호출은 반드시 `scripts/probe-kis-vts-futures-connection.py`(잔고 조회만,
읽기 전용)로 연결을 확인한 뒤에, 그 다음도 반드시 `--dry-run`으로
요청 바디를 눈으로 확인한 뒤에만 실주문으로 넘어간다.

엔드포인트·TR_ID:
    선물옵션 주문        POST /uapi/domestic-futureoption/v1/trading/order
                        TR_ID VTTO1101U (모의투자, 주간만 - 야간은 모의 미지원)
    선물옵션 잔고현황    GET  /uapi/domestic-futureoption/v1/trading/inquire-balance
                        TR_ID VTFO6118R
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
TOKEN_CACHE = REPO_ROOT / ".token_cache_kis_vts_futures.json"
KST = timezone(timedelta(hours=9))

BASE_URL = "https://openapivts.koreainvestment.com:29443"
PATH_ORDER = "/uapi/domestic-futureoption/v1/trading/order"
PATH_BALANCE = "/uapi/domestic-futureoption/v1/trading/inquire-balance"
TR_ORDER = "VTTO1101U"       # 모의투자·주간(day)만 지원 - 야간(STTN...)은 실전 전용
TR_BALANCE = "VTFO6118R"
TR_BOARD_FUTURES = "FHPIF05030200"   # 국내옵션전광판_선물 - 실전/모의 구분 없는 공개 시세
PATH_BOARD_FUTURES = "/uapi/domestic-futureoption/v1/quotations/display-board-futures"
# "MKI"는 미니선물(승수 5만) 전광판이었다(2026-09-13 실측, hts_kor_isnm="미니F ...") -
# 표준 코스피200선물(승수 25만, 이 랩의 백테스트가 쓰는 그 상품)은 "K2I"가 맞는
# market class code (실측: hts_kor_isnm="F 202612" 등, 가격 스케일이 .cache/
# kospi200_daily의 동일 월물 종가와 일치 확인).
BOARD_MARKET_CLASS_STANDARD = "K2I"
MAX_BALANCE_PAGES = 20


class _RateLimiter:
    """계좌 단위 1건/초 - kisVtsClient.py와 동일 근거(2026-08-21 확인)로
    1.2초 마진. 선물 계좌는 별도 앱키라 이 리미터도 별도 인스턴스여야
    한다(주식 클라이언트의 리미터를 공유하면 안 된다 - 서로 다른 계좌의
    유량을 하나로 묶어 불필요하게 느려진다)."""
    def __init__(self, min_interval_sec=1.2):
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


class KisVtsFuturesError(RuntimeError):
    pass


def _request(method, url, **kwargs):
    _RATE_LIMITER.wait()
    return requests.request(method, url, **kwargs)


_RETRYABLE = {"EGW00201", "EGW00300"}


def _call(method, url, label, retries=3, **kwargs):
    """읽기 전용 호출만 재시도한다(kisVtsClient.py와 동일 원칙 -
    주문은 재시도가 중복체결 위험을 키우므로 여기서 쓰지 않는다)."""
    for attempt in range(retries):
        try:
            r = _request(method, url, **kwargs)
        except requests.RequestException as e:
            if attempt >= retries - 1:
                raise KisVtsFuturesError(f"{label}: 전송 실패 {e}") from e
            time.sleep(_RATE_LIMITER.min_interval_sec * (attempt + 1))
            continue
        resp = r.json()
        if r.status_code == 200 and resp.get("rt_cd") == "0":
            return r, resp
        if resp.get("msg_cd") in _RETRYABLE and attempt < retries - 1:
            time.sleep(_RATE_LIMITER.min_interval_sec * (attempt + 1))
            continue
        raise KisVtsFuturesError(f"{label}: {resp.get('msg_cd')} {resp.get('msg1')}")


def _load_env():
    env = {}
    p = REPO_ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    for k in ("KIS_VTS_FUTURES_APP_KEY", "KIS_VTS_FUTURES_APP_SECRET", "KIS_VTS_FUTURES_ACCOUNT_NO"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


class KisVtsFuturesClient:
    def __init__(self):
        env = _load_env()
        self.key = env.get("KIS_VTS_FUTURES_APP_KEY", "")
        self.secret = env.get("KIS_VTS_FUTURES_APP_SECRET", "")
        account_raw = env.get("KIS_VTS_FUTURES_ACCOUNT_NO", "")
        if not (self.key and self.secret and account_raw):
            raise KisVtsFuturesError(
                "KIS_VTS_FUTURES_APP_KEY/APP_SECRET/ACCOUNT_NO 중 하나가 .env에 없다. "
                "scripts/setup-keys-interactive.py 로 'KIS 모의투자(VTS) - 선물' 항목을 먼저 채운다. "
                "(선물옵션 모의투자 계좌 자체가 없으면 한국투자증권에서 먼저 개설해야 한다.)")
        if "-" in account_raw:
            self.cano, self.acnt_prdt_cd = account_raw.split("-", 1)
        else:
            self.cano, self.acnt_prdt_cd = account_raw, "03"  # 선물옵션 기본 상품코드
        self._token = None

    def _get_token(self):
        if self._token:
            return self._token
        if TOKEN_CACHE.exists():
            try:
                c = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
                exp = datetime.fromisoformat(c["expiresAt"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=KST)
                if exp - timedelta(minutes=10) > datetime.now(KST) and c.get("appKeyTail") == self.key[-4:]:
                    self._token = c["accessToken"]
                    return self._token
            except Exception:
                pass
        r = _request("POST", BASE_URL + "/oauth2/tokenP",
                      data=json.dumps({"grant_type": "client_credentials",
                                        "appkey": self.key, "appsecret": self.secret}),
                      headers={"content-type": "application/json"}, timeout=20)
        body = r.json()
        if r.status_code != 200 or "access_token" not in body:
            raise KisVtsFuturesError("토큰 발급 실패: " + str(body.get("error_description", body)))
        self._token = body["access_token"]
        TOKEN_CACHE.write_text(json.dumps({
            "accessToken": self._token,
            "expiresAt": body.get("access_token_token_expired", ""),
            "issuedAt": datetime.now(KST).isoformat(),
            "appKeyTail": self.key[-4:],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            os.chmod(TOKEN_CACHE, 0o600)
        except Exception:
            pass
        return self._token

    def _headers(self, tr_id):
        return {
            "content-type": "application/json; charset=utf-8",
            "authorization": "Bearer " + self._get_token(),
            "appkey": self.key,
            "appsecret": self.secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    def inquire_balance(self, mgna_dvsn="01", excc_stat_cd="2"):
        """선물옵션 잔고현황. mgna_dvsn: 01=게시증거금/02=유지증거금.
        excc_stat_cd: 1=정산/2=본정산(KIS 예제 기본값). 반환: (positions, summary)
        - positions: output1 리스트(보유 종목별), summary: output2 dict(예수금·평가금 등)."""
        params = {
            "CANO": self.cano, "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "MGNA_DVSN": mgna_dvsn, "EXCC_STAT_CD": excc_stat_cd,
            "CTX_AREA_FK200": "", "CTX_AREA_NK200": "",
        }
        positions = []
        headers = self._headers(TR_BALANCE)
        summary = {}
        for page in range(1, MAX_BALANCE_PAGES + 1):
            r, resp = _call("GET", BASE_URL + PATH_BALANCE, f"선물 잔고 조회 실패(page {page})",
                             headers=headers, params=params, timeout=20)
            positions += resp.get("output1", [])
            summary = (resp.get("output2") or [{}])
            summary = summary[0] if isinstance(summary, list) else summary
            if r.headers.get("tr_cont") not in ("F", "M"):
                break
            headers = {**self._headers(TR_BALANCE), "tr_cont": "N"}
            params = {**params, "CTX_AREA_FK200": resp.get("ctx_area_fk200", ""),
                                "CTX_AREA_NK200": resp.get("ctx_area_nk200", "")}
        else:
            raise KisVtsFuturesError(f"선물 잔고 연속조회가 {MAX_BALANCE_PAGES}페이지에서 안 끝났다 "
                                       f"(누적 {len(positions)}건) - 부분 잔고를 반환하지 않는다")
        return positions, summary

    def resolve_front_month(self):
        """표준 코스피200선물(승수 25만) 전광판을 조회해 **당일 최대거래량**
        월물을 front로 고른다 - 이 랩의 백테스트(stage5_1의 front_series,
        "일자별 최대거래량 주간 계약")와 정확히 같은 규칙. 시세 조회는
        실전/모의 구분이 없는 공개 엔드포인트라 이 클라이언트(선물 VTS
        앱키)로 불러도 항상 동작한다.

        반환: dict(code=futs_shrn_iscd, name=hts_kor_isnm, price=float(futs_prpr),
        volume=int(acml_vol)) - 그중 거래량 최대 1건."""
        headers = self._headers(TR_BOARD_FUTURES)
        params = {"FID_COND_MRKT_DIV_CODE": "F", "FID_COND_SCR_DIV_CODE": "20503",
                  "FID_COND_MRKT_CLS_CODE": BOARD_MARKET_CLASS_STANDARD}
        _, resp = _call("GET", BASE_URL + PATH_BOARD_FUTURES, "선물 전광판 조회 실패",
                         headers=headers, params=params, timeout=20)
        rows = resp.get("output", [])
        if not rows:
            raise KisVtsFuturesError("선물 전광판이 빈 응답을 줬다 - 장 운영시간 밖일 수 있음")
        front = max(rows, key=lambda r: int(r.get("acml_vol") or 0))
        return {"code": front["futs_shrn_iscd"], "name": front["hts_kor_isnm"],
                "price": float(front["futs_prpr"]), "volume": int(front["acml_vol"] or 0),
                "ask": float(front["futs_askp"]), "bid": float(front["futs_bidp"])}

    def build_order_body(self, side, shtn_pdno, quantity, limit_price):
        """주문 요청 바디를 만들기만 한다(전송 안 함) - dry-run·리뷰용.
        side: 'BUY'|'SELL' -> SLL_BUY_DVSN_CD 02/01. 기본은 지정가
        (NMPR_TYPE_CD=01, ORD_DVSN_CD=01) - 모의투자 시장가 지원 여부가
        미검증이라 가장 보편적으로 통하는 지정가를 기본값으로 둔다."""
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        return {
            "ORD_PRCS_DVSN_CD": "02",
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "SLL_BUY_DVSN_CD": "02" if side == "BUY" else "01",
            "SHTN_PDNO": shtn_pdno,
            "ORD_QTY": str(quantity),
            "UNIT_PRICE": str(limit_price),
            "NMPR_TYPE_CD": "01",       # 01=지정가
            "KRX_NMPR_CNDT_CD": "0",    # 0=조건 없음
            "ORD_DVSN_CD": "01",        # 01=지정가
            "CTAC_TLNO": "",
            "FUOP_ITEM_DVSN_CD": "",
        }

    def order(self, side, shtn_pdno, quantity, limit_price, dry_run=True):
        """dry_run=True(기본값)면 실제 전송 없이 바디만 반환한다 - 호출부가
        실주문 여부를 명시적으로 선택해야 한다(기본값이 안전한 쪽)."""
        body = self.build_order_body(side, shtn_pdno, quantity, limit_price)
        if dry_run:
            return {"dryRun": True, "requestBody": body}
        r = _request("POST", BASE_URL + PATH_ORDER, headers=self._headers(TR_ORDER),
                      data=json.dumps(body), timeout=20)
        resp = r.json()
        if r.status_code != 200 or resp.get("rt_cd") != "0":
            raise KisVtsFuturesError(f"{side} 선물 주문 실패: {resp.get('msg_cd')} {resp.get('msg1')}")
        return {"dryRun": False, "requestBody": body, "response": resp}
