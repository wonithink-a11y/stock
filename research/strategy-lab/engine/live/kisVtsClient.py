"""KIS 모의투자(VTS) REST 클라이언트 - 인증·주문·잔고조회.

라이브 도메인(openapi.koreainvestment.com)은 이 파일 어디에도 등장하지
않는다 - 하드코딩된 상수 하나(BASE_URL)뿐이고 그게 항상 VTS 도메인이다.
KIS_VTS_APP_KEY/KIS_VTS_APP_SECRET/KIS_VTS_ACCOUNT_NO만 읽는다 - 라이브
키(KIS_APP_KEY)는 이 모듈이 존재를 몰라야 한다(실수로 라이브를 칠 방법이
코드에 없어야 안전하다).

엔드포인트·TR_ID·요청 필드는 KIS 공식 예제
(github.com/koreainvestment/open-trading-api, examples_user/kis_auth.py ·
examples_user/domestic_stock/domestic_stock_functions.py, 2026-08-21 확인)
그대로다:
    주문   POST /uapi/domestic-stock/v1/trading/order-cash
           TR_ID 매수 VTTC0012U · 매도 VTTC0011U (둘 다 모의투자 전용)
    잔고   GET  /uapi/domestic-stock/v1/trading/inquire-balance
           TR_ID VTTC8434R
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
TOKEN_CACHE = REPO_ROOT / ".token_cache_kis_vts.json"
KST = timezone(timedelta(hours=9))

BASE_URL = "https://openapivts.koreainvestment.com:29443"
PATH_ORDER = "/uapi/domestic-stock/v1/trading/order-cash"
PATH_BALANCE = "/uapi/domestic-stock/v1/trading/inquire-balance"
PATH_PRICE = "/uapi/domestic-stock/v1/quotations/inquire-price"
TR_BUY = "VTTC0012U"
TR_SELL = "VTTC0011U"
TR_BALANCE = "VTTC8434R"
# 시세 조회는 실전/모의 구분이 없다(계정에 안 묶인 공개 시세라 KIS가 같은
# TR_ID를 쓴다) - 그래도 도메인은 항상 BASE_URL(모의투자)로만 부른다.
TR_PRICE = "FHKST01010100"


class KisVtsError(RuntimeError):
    pass


def _load_env():
    env = {}
    p = REPO_ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    for k in ("KIS_VTS_APP_KEY", "KIS_VTS_APP_SECRET", "KIS_VTS_ACCOUNT_NO"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


class KisVtsClient:
    def __init__(self):
        env = _load_env()
        self.key = env.get("KIS_VTS_APP_KEY", "")
        self.secret = env.get("KIS_VTS_APP_SECRET", "")
        account_raw = env.get("KIS_VTS_ACCOUNT_NO", "")
        if not (self.key and self.secret and account_raw):
            raise KisVtsError(
                "KIS_VTS_APP_KEY/KIS_VTS_APP_SECRET/KIS_VTS_ACCOUNT_NO 중 하나가 .env에 없다. "
                "scripts/setup-kis-vts-key.py 를 먼저 실행한다.")
        if "-" in account_raw:
            self.cano, self.acnt_prdt_cd = account_raw.split("-", 1)
        else:
            self.cano, self.acnt_prdt_cd = account_raw, "01"
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

        r = requests.post(BASE_URL + "/oauth2/tokenP",
                           data=json.dumps({"grant_type": "client_credentials",
                                             "appkey": self.key, "appsecret": self.secret}),
                           headers={"content-type": "application/json"}, timeout=20)
        body = r.json()
        if r.status_code != 200 or "access_token" not in body:
            raise KisVtsError("토큰 발급 실패: " + str(body.get("error_description", body)))
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

    def order_cash(self, side, symbol, quantity, ord_dvsn="01", ord_unpr="0"):
        """side: 'BUY' | 'SELL'. ord_dvsn '01'=시장가(기본, ord_unpr는 '0'),
        '00'=지정가(ord_unpr에 실제 가격을 넣는다). 반환: KIS 응답 dict 그대로
        (output에 주문번호 KRX_FWDG_ORD_ORGNO·ODNO가 있다)."""
        if side not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        tr_id = TR_BUY if side == "BUY" else TR_SELL
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(ord_unpr),
        }
        r = requests.post(BASE_URL + PATH_ORDER, headers=self._headers(tr_id),
                           data=json.dumps(body), timeout=20)
        resp = r.json()
        if r.status_code != 200 or resp.get("rt_cd") != "0":
            raise KisVtsError(f"{side} 주문 실패: {resp.get('msg_cd')} {resp.get('msg1')}")
        return resp

    def inquire_balance(self):
        """반환: (holdings: list[dict], cash: str, eval_total: str)."""
        params = {
            "CANO": self.cano, "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
        }
        r = requests.get(BASE_URL + PATH_BALANCE, headers=self._headers(TR_BALANCE),
                          params=params, timeout=20)
        resp = r.json()
        if r.status_code != 200 or resp.get("rt_cd") != "0":
            raise KisVtsError(f"잔고 조회 실패: {resp.get('msg_cd')} {resp.get('msg1')}")
        holdings = [h for h in resp.get("output1", []) if h.get("hldg_qty", "0") != "0"]
        summary = resp.get("output2") or [{}]
        return holdings, summary[0].get("dnca_tot_amt"), summary[0].get("tot_evlu_amt")

    def get_current_price(self, symbol):
        """현재가(stck_prpr) 하나만 float로 반환한다. 시세 조회는 실전/모의
        구분이 없는 공개 엔드포인트라 TR_ID가 하나뿐이다 - 그래도 호출은
        항상 BASE_URL(모의투자 도메인)로만 나간다."""
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol}
        r = requests.get(BASE_URL + PATH_PRICE, headers=self._headers(TR_PRICE),
                          params=params, timeout=20)
        resp = r.json()
        if r.status_code != 200 or resp.get("rt_cd") != "0":
            raise KisVtsError(f"시세 조회 실패({symbol}): {resp.get('msg_cd')} {resp.get('msg1')}")
        return float(resp["output"]["stck_prpr"])

    def get_order_status(self, order_no, order_date_yyyymmdd, requested_qty):
        """order_no(주문번호)로 그날의 체결 상세를 조회한다(inquire-daily-ccld,
        3개월 이내). 반환: {"fullyFilled": bool, "rejected": bool,
        "filledQty": int, "avgPrice": float|None, "pending": bool} -
        네 상태가 서로 배타적이 아니다(부분체결은 filledQty>0이면서
        pending=True일 수 있다) - 호출부가 우선순위를 정한다."""
        params = {
            "CANO": self.cano, "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "INQR_STRT_DT": order_date_yyyymmdd, "INQR_END_DT": order_date_yyyymmdd,
            "SLL_BUY_DVSN_CD": "00", "PDNO": "", "CCLD_DVSN": "00",
            "INQR_DVSN": "00", "INQR_DVSN_3": "00", "ORD_GNO_BRNO": "",
            "ODNO": order_no, "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": "", "EXCG_ID_DVSN_CD": "KRX",
        }
        r = requests.get(BASE_URL + "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
                          headers=self._headers("VTTC0081R"), params=params, timeout=20)
        resp = r.json()
        if r.status_code != 200 or resp.get("rt_cd") != "0":
            raise KisVtsError(f"체결조회 실패(주문번호 {order_no}): {resp.get('msg_cd')} {resp.get('msg1')}")
        rows = [row for row in resp.get("output1", []) if row.get("odno") == order_no]
        if not rows:
            # 접수 직후라 아직 조회에 안 잡힐 수 있다 - 실패가 아니라 "아직 모름".
            return {"fullyFilled": False, "rejected": False, "filledQty": 0,
                    "avgPrice": None, "pending": True}
        row = rows[0]
        filled_qty = int(row.get("tot_ccld_qty") or 0)
        remaining_qty = int(row.get("rmn_qty") or 0)
        rejected_qty = int(row.get("rjct_qty") or 0)
        avg_price = float(row["avg_prvs"]) if filled_qty > 0 and row.get("avg_prvs") else None
        fully_filled = remaining_qty == 0 and filled_qty >= int(requested_qty) and rejected_qty == 0
        rejected = rejected_qty > 0 and filled_qty == 0
        return {"fullyFilled": fully_filled, "rejected": rejected, "filledQty": filled_qty,
                "avgPrice": avg_price, "pending": not fully_filled and not rejected}
