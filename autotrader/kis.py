"""한국투자증권(KIS) Open API 어댑터 — 국내(KR)·해외 나스닥(US), 모의/실전 겸용.

★ 이 파일의 실전 TR_ID 는 **공식 문서로 대조하지 못했다**(설계 문서 §3). 모의 값은 기존 클라이언트로 검증됐고,
   실전 값은 KIS 의 "모의 앞 글자 V → T" 규칙과 기존 코드 주석에서 가져왔다. 그래서 실전 주문에는 사용자의 대조
   확인(`live.tr_ids_reviewed`)이 게이트로 걸려 있다(config.gate_problems). 조회 TR_ID 가 틀리면 조회가 실패할 뿐이다.
★ 주문은 재시도하지 않는다(중복 매수의 대가가 조회 실패보다 훨씬 크다). 조회만 EGW00201/EGW00300 에서 재시도.
★ 실전 주문은 어댑터도 한 번 더 잠근다: `orders_enabled` 가 True 로 만들어진 인스턴스만 실주문을 낸다
   (CLI 가 게이트를 통과한 `--execute` 실행에만 True 를 준다).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from .broker import Broker
from .config import REPO_ROOT, key_names, state_dir
from .models import Intent, OpenOrder, Position

KST = timezone(timedelta(hours=9))

DOMAINS = {
    "paper": "https://openapivts.koreainvestment.com:29443",
    "live": "https://openapi.koreainvestment.com:9443",
}

# (시장, 용도) -> (모의 TR_ID, 실전 TR_ID). 실전 값은 미확인(모듈 docstring).
TR_IDS: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("KR", "buy"): ("VTTC0012U", "TTTC0012U"),
    ("KR", "sell"): ("VTTC0011U", "TTTC0011U"),
    ("KR", "balance"): ("VTTC8434R", "TTTC8434R"),
    ("KR", "ccld"): ("VTTC0081R", "TTTC0081R"),
    ("KR", "price"): ("FHKST01010100", "FHKST01010100"),
    ("US", "buy"): ("VTTT1002U", "TTTT1002U"),
    ("US", "sell"): ("VTTT1001U", "TTTT1006U"),
    ("US", "cancel"): ("VTTT1004U", "TTTT1004U"),
    ("US", "balance"): ("VTTS3012R", "TTTS3012R"),
    ("US", "nccs"): ("VTTS3018R", "TTTS3018R"),
    ("US", "psamount"): ("VTTS3007R", "TTTS3007R"),
    ("US", "price"): ("HHDFS00000300", "HHDFS00000300"),
}
QUOTE_KEYS = {("KR", "price"), ("US", "price")}       # 모의/실전 구분 없는 시세 TR

PATHS = {
    ("KR", "order"): "/uapi/domestic-stock/v1/trading/order-cash",
    ("KR", "balance"): "/uapi/domestic-stock/v1/trading/inquire-balance",
    ("KR", "ccld"): "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
    ("KR", "price"): "/uapi/domestic-stock/v1/quotations/inquire-price",
    ("US", "order"): "/uapi/overseas-stock/v1/trading/order",
    ("US", "cancel"): "/uapi/overseas-stock/v1/trading/order-rvsecncl",
    ("US", "balance"): "/uapi/overseas-stock/v1/trading/inquire-balance",
    ("US", "nccs"): "/uapi/overseas-stock/v1/trading/inquire-nccs",
    ("US", "psamount"): "/uapi/overseas-stock/v1/trading/inquire-psamount",
    ("US", "price"): "/uapi/overseas-price/v1/quotations/price",
}

_RETRYABLE = {"EGW00201", "EGW00300"}
MAX_PAGES = 100
US_EXCHANGE = "NASD"          # 주문·잔고용
US_QUOTE_EXCHANGE = "NAS"     # 시세용 코드가 다르다


class KisError(RuntimeError):
    pass


def tr_id(market: str, purpose: str, mode: str) -> str:
    pair = TR_IDS[(market, purpose)]
    return pair[0] if mode == "paper" else pair[1]


def _i(x, default=0) -> int:
    try:
        return int(float(str(x).strip() or default))
    except (TypeError, ValueError):
        return default


def _f(x, default=0.0) -> float:
    try:
        return float(str(x).strip() or default)
    except (TypeError, ValueError):
        return default


class KisClient:
    def __init__(self, mode: str, key: str, secret: str, account: str, token_dir: Path,
                 http: Optional[Callable] = None, sleep: Callable[[float], None] = time.sleep,
                 min_interval: Optional[float] = None):
        if mode not in ("paper", "live"):
            raise ValueError("mode 는 paper|live")
        if not (key and secret and account):
            raise KisError("앱키·시크릿·계좌번호가 필요하다")
        self.mode = mode
        self.key, self.secret = key, secret
        acc = account.split("-", 1)
        self.cano, self.prdt = acc[0], (acc[1] if len(acc) > 1 else "01")
        self.base = DOMAINS[mode]
        self.token_file = Path(token_dir) / f"token_{mode}.json"
        self._http = http or self._default_http
        self._sleep = sleep
        self._min = min_interval if min_interval is not None else (1.2 if mode == "paper" else 0.2)
        self._last = 0.0
        self._token: Optional[str] = None

    @staticmethod
    def _default_http(method, url, **kw):
        import requests
        return requests.request(method, url, **kw)

    def _request(self, method, url, **kw):
        wait = self._last + self._min - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()
        return self._http(method, url, **kw)

    def _get_token(self) -> str:
        if self._token:
            return self._token
        if self.token_file.exists():
            try:
                c = json.loads(self.token_file.read_text(encoding="utf-8"))
                exp = datetime.strptime(c["expiresAt"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
                if exp - timedelta(minutes=10) > datetime.now(KST) and c.get("appKeyTail") == self.key[-4:]:
                    self._token = c["accessToken"]
                    return self._token
            except (ValueError, KeyError, OSError):
                pass
        r = self._request("POST", self.base + "/oauth2/tokenP",
                          data=json.dumps({"grant_type": "client_credentials",
                                           "appkey": self.key, "appsecret": self.secret}),
                          headers={"content-type": "application/json"}, timeout=20)
        body = r.json()
        if r.status_code != 200 or "access_token" not in body:
            raise KisError("토큰 발급 실패: " + str(body.get("error_description", body.get("msg1", "")))[:200])
        self._token = body["access_token"]
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({
            "accessToken": self._token, "expiresAt": body.get("access_token_token_expired", ""),
            "appKeyTail": self.key[-4:]}, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(self.token_file, 0o600)
        except OSError:
            pass
        return self._token

    def headers(self, tr: str, extra: Optional[dict] = None) -> dict:
        h = {"content-type": "application/json; charset=utf-8", "authorization": "Bearer " + self._get_token(),
             "appkey": self.key, "appsecret": self.secret, "tr_id": tr, "custtype": "P"}
        if extra:
            h.update(extra)
        return h

    def get(self, market: str, purpose: str, params: dict, label: str, retries: int = 3,
            extra_headers: Optional[dict] = None):
        """조회(GET). EGW00201/00300·전송 오류는 재시도한다. (response, body) 반환."""
        tr = tr_id(market, purpose, self.mode)
        url = self.base + PATHS[(market, purpose)]
        for attempt in range(retries):
            try:
                r = self._request("GET", url, headers=self.headers(tr, extra_headers), params=params, timeout=20)
            except Exception as e:                      # noqa: BLE001 — 전송 오류
                if attempt >= retries - 1:
                    raise KisError(f"{label}: 전송 실패 {e}") from e
                self._sleep(self._min * (attempt + 1))
                continue
            body = r.json()
            if r.status_code == 200 and body.get("rt_cd") == "0":
                return r, body
            if body.get("msg_cd") in _RETRYABLE and attempt < retries - 1:
                self._sleep(self._min * (attempt + 1))
                continue
            raise KisError(f"{label}: {body.get('msg_cd')} {body.get('msg1')}")
        raise KisError(f"{label}: 재시도 소진")

    def post(self, market: str, purpose: str, payload: dict, label: str, tr_purpose: Optional[str] = None) -> dict:
        """주문·취소(POST). **재시도하지 않는다.**"""
        tr = tr_id(market, tr_purpose or purpose, self.mode)
        r = self._request("POST", self.base + PATHS[(market, purpose)], headers=self.headers(tr),
                          data=json.dumps(payload), timeout=20)
        body = r.json()
        if r.status_code != 200 or body.get("rt_cd") != "0":
            raise KisError(f"{label}: {body.get('msg_cd')} {body.get('msg1')}")
        return body

    def paginate(self, market: str, purpose: str, params: dict, label: str, list_key: str,
                 cursor: Tuple[str, str], req_cursor: Tuple[str, str]) -> List[dict]:
        """연속조회를 끝까지 따라간다. 상한에 걸리면 잘린 목록을 전체인 척 돌려주지 않고 실패시킨다."""
        rows: List[dict] = []
        extra = None
        p = dict(params)
        for page in range(1, MAX_PAGES + 1):
            r, body = self.get(market, purpose, p, f"{label}(page {page})", extra_headers=extra)
            out = body.get(list_key) or []
            rows += [out] if isinstance(out, dict) else out
            if (r.headers.get("tr_cont") or "").strip() not in ("F", "M"):
                return rows
            extra = {"tr_cont": "N"}
            p = {**p, req_cursor[0]: body.get(cursor[0], ""), req_cursor[1]: body.get(cursor[1], "")}
        raise KisError(f"{label}: {MAX_PAGES}페이지에서 안 끝났다 — 부분 결과를 돌려주지 않는다")


class KisBroker(Broker):
    name = "kis"

    def __init__(self, client: KisClient, orders_enabled: bool = False):
        self.c = client
        self.mode = client.mode
        self.orders_enabled = orders_enabled

    # ---------------------------------------------------------------- 조회
    def positions(self, market: str) -> List[Position]:
        if market == "KR":
            params = {"CANO": self.c.cano, "ACNT_PRDT_CD": self.c.prdt, "AFHR_FLPR_YN": "N", "OFL_YN": "",
                      "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                      "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
            rows = self.c.paginate("KR", "balance", params, "국내 잔고", "output1",
                                   ("ctx_area_fk100", "ctx_area_nk100"), ("CTX_AREA_FK100", "CTX_AREA_NK100"))
            return [Position((r.get("pdno") or "").strip(), "KR", _i(r.get("hldg_qty")), _f(r.get("pchs_avg_pric")))
                    for r in rows if _i(r.get("hldg_qty")) > 0]
        params = {"CANO": self.c.cano, "ACNT_PRDT_CD": self.c.prdt, "OVRS_EXCG_CD": US_EXCHANGE,
                  "TR_CRCY_CD": "USD", "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}
        rows = self.c.paginate("US", "balance", params, "해외 잔고", "output1",
                               ("ctx_area_fk200", "ctx_area_nk200"), ("CTX_AREA_FK200", "CTX_AREA_NK200"))
        return [Position((r.get("ovrs_pdno") or "").strip(), "US", _i(r.get("ovrs_cblc_qty")), _f(r.get("pchs_avg_pric")))
                for r in rows if _i(r.get("ovrs_cblc_qty")) > 0]

    def cash(self, market: str, ref_symbol: Optional[str] = None) -> float:
        if market == "KR":
            params = {"CANO": self.c.cano, "ACNT_PRDT_CD": self.c.prdt, "AFHR_FLPR_YN": "N", "OFL_YN": "",
                      "INQR_DVSN": "02", "UNPR_DVSN": "01", "FUND_STTL_ICLD_YN": "N",
                      "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00", "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""}
            _, body = self.c.get("KR", "balance", params, "국내 예수금")
            s = (body.get("output2") or [{}])[0]
            # 예수금이 둘이다 — D+0(dnca_tot_amt)와 D+2(prvs_rcdl_excc_amt). 보수적으로 작은 쪽을 쓴다.
            return float(min(_i(s.get("dnca_tot_amt")), _i(s.get("prvs_rcdl_excc_amt"))))
        if not ref_symbol:
            raise KisError("해외 주문가능 금액은 기준 종목(ref_symbol)이 필요하다")
        px = self.quote(ref_symbol, "US")
        params = {"CANO": self.c.cano, "ACNT_PRDT_CD": self.c.prdt, "OVRS_EXCG_CD": US_EXCHANGE,
                  "OVRS_ORD_UNPR": f"{px:.2f}", "ITEM_CD": ref_symbol}
        _, body = self.c.get("US", "psamount", params, "해외 매수가능")
        return _f((body.get("output") or {}).get("ord_psbl_frcr_amt"))

    def open_orders(self, market: str) -> List[OpenOrder]:
        if market == "KR":
            today = datetime.now(KST).strftime("%Y%m%d")
            params = {"CANO": self.c.cano, "ACNT_PRDT_CD": self.c.prdt, "INQR_STRT_DT": today, "INQR_END_DT": today,
                      "SLL_BUY_DVSN_CD": "00", "PDNO": "", "CCLD_DVSN": "02", "INQR_DVSN": "00",
                      "INQR_DVSN_3": "00", "ORD_GNO_BRNO": "", "ODNO": "", "INQR_DVSN_1": "",
                      "CTX_AREA_FK100": "", "CTX_AREA_NK100": "", "EXCG_ID_DVSN_CD": "KRX"}
            rows = self.c.paginate("KR", "ccld", params, "국내 미체결", "output1",
                                   ("ctx_area_fk100", "ctx_area_nk100"), ("CTX_AREA_FK100", "CTX_AREA_NK100"))
            return [OpenOrder((r.get("odno") or "").strip(), (r.get("pdno") or "").strip(), "KR",
                              "SELL" if r.get("sll_buy_dvsn_cd") == "01" else "BUY",
                              _i(r.get("ord_qty")), _i(r.get("tot_ccld_qty")), _f(r.get("ord_unpr")))
                    for r in rows if _i(r.get("rmn_qty")) > 0 and r.get("cncl_yn") != "Y"]
        params = {"CANO": self.c.cano, "ACNT_PRDT_CD": self.c.prdt, "OVRS_EXCG_CD": US_EXCHANGE, "SORT_SQN": "DS",
                  "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""}
        rows = self.c.paginate("US", "nccs", params, "해외 미체결", "output",
                               ("ctx_area_fk200", "ctx_area_nk200"), ("CTX_AREA_FK200", "CTX_AREA_NK200"))
        return [OpenOrder((r.get("odno") or "").strip(), (r.get("pdno") or "").strip(), "US",
                          "SELL" if r.get("sll_buy_dvsn_cd") == "01" else "BUY",
                          _i(r.get("ft_ord_qty")), _i(r.get("ft_ccld_qty")), _f(r.get("ft_ord_unpr3")))
                for r in rows]

    def quote(self, symbol: str, market: str) -> float:
        if market == "KR":
            _, body = self.c.get("KR", "price", {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": symbol},
                                 f"국내 시세({symbol})")
            return _f((body.get("output") or {}).get("stck_prpr"))
        _, body = self.c.get("US", "price", {"AUTH": "", "EXCD": US_QUOTE_EXCHANGE, "SYMB": symbol},
                             f"해외 시세({symbol})")
        return _f((body.get("output") or {}).get("last"))

    # ---------------------------------------------------------------- 주문
    def _guard_orders(self, dry_run: bool) -> None:
        if dry_run:
            return
        if not self.orders_enabled:
            raise KisError("이 브로커 인스턴스는 주문이 잠겨 있다(orders_enabled=False) — 실행 게이트를 통과한 --execute 에서만 열린다")

    def place(self, intent: Intent, dry_run: bool = True) -> dict:
        bad = intent.validate()
        if bad:
            raise ValueError(bad)
        if intent.order_type == "loc" and self.mode != "live":
            raise KisError("loc(LOC) 는 실전 전용이다 — 모의투자는 지정가만 받는다")
        payload = self._order_payload(intent)
        if dry_run:
            return {"dryRun": True, "symbol": intent.symbol, "side": intent.side, "qty": intent.qty,
                    "mode": self.mode, "payload": {k: v for k, v in payload.items() if k not in ("CANO",)}}
        self._guard_orders(dry_run)
        purpose = "buy" if intent.side == "BUY" else "sell"
        body = self.c.post(intent.market, "order", payload,
                           f"{intent.side} 주문({intent.symbol} {intent.qty})", tr_purpose=purpose)
        out = body.get("output") or {}
        return {"dryRun": False, "orderNo": (out.get("ODNO") or "").strip(), "symbol": intent.symbol,
                "side": intent.side, "qty": intent.qty, "market": intent.market,
                "orderTime": (out.get("ORD_TMD") or "").strip()}

    def _order_payload(self, it: Intent) -> dict:
        base = {"CANO": self.c.cano, "ACNT_PRDT_CD": self.c.prdt, "PDNO": it.symbol, "ORD_QTY": str(int(it.qty))}
        if it.market == "KR":
            if it.order_type == "market":
                return {**base, "ORD_DVSN": "01", "ORD_UNPR": "0"}
            return {**base, "ORD_DVSN": "00", "ORD_UNPR": str(int(round(it.limit_price)))}
        dvsn = "34" if it.order_type == "loc" else "00"
        payload = {**base, "OVRS_EXCG_CD": US_EXCHANGE, "OVRS_ORD_UNPR": f"{it.limit_price:.2f}",
                   "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": dvsn}
        if it.side == "SELL":
            payload["SLL_TYPE"] = "00"        # 해외 매도 표시 — 미확인 필드(README §실전 전환)
        return payload

    def cancel(self, order: OpenOrder, dry_run: bool = True) -> dict:
        if order.market != "US":
            raise KisError("국내 주문 취소는 지원하지 않는다(당일물 — 장 마감에 소멸)")
        payload = {"CANO": self.c.cano, "ACNT_PRDT_CD": self.c.prdt, "OVRS_EXCG_CD": US_EXCHANGE,
                   "PDNO": order.symbol, "ORGN_ODNO": order.order_no, "RVSE_CNCL_DVSN_CD": "02",
                   "ORD_QTY": str(order.remaining), "OVRS_ORD_UNPR": "0", "MGCO_APTM_ODNO": "",
                   "ORD_SVR_DVSN_CD": "0"}
        if dry_run:
            return {"dryRun": True, "orderNo": order.order_no, "payload": payload}
        self._guard_orders(dry_run)
        self.c.post("US", "cancel", payload, f"취소({order.symbol} {order.order_no})")
        return {"dryRun": False, "orderNo": order.order_no}


def make_broker(cfg: dict, env: Dict[str, str], execute: bool, repo_root: Path = REPO_ROOT,
                http: Optional[Callable] = None) -> KisBroker:
    """설정의 mode·key_prefix 에 맞는 키로 브로커를 만든다. 주문 잠금 해제(orders_enabled)는 --execute 일 때만."""
    mode = cfg["mode"]
    keys = key_names(cfg)
    client = KisClient(mode, env[keys[0]], env[keys[1]], env[keys[2]], state_dir(cfg, repo_root), http=http)
    return KisBroker(client, orders_enabled=execute)
