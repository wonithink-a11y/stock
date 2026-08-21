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
TR_BUY = "VTTC0012U"
TR_SELL = "VTTC0011U"
TR_BALANCE = "VTTC8434R"


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
