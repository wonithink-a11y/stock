"""KIS 모의투자(VTS) **해외주식** REST 클라이언트 - 조회·주문.

kisVtsClient.py 의 설계 원칙을 그대로 따른다:
  - 라이브 도메인은 이 파일 어디에도 없다. BASE_URL 을 그 모듈에서 가져오고
    그건 항상 VTS 도메인이다 - 실수로 라이브를 칠 방법이 코드에 없다.
  - HTTP 는 그 모듈의 `_request`(레이트리미터 포함) 하나만 거친다.
  - **주문은 재시도하지 않는다.** EGW00201 이 "접수 전에 막혔다"는 뜻인지 확신할 수
    없고, 확신 없는 재시도의 대가(중복 매수)가 조회 실패보다 훨씬 크다.

엔드포인트·TR_ID 는 KIS 공식 예제
(github.com/koreainvestment/open-trading-api, examples_user/overseas_stock/
overseas_stock_functions.py, 2026-09-12 확인) 그대로다:

    주문      POST /uapi/overseas-stock/v1/trading/order
              미국 매수 VTTT1002U · 미국 매도 VTTT1001U (둘 다 모의투자 전용)
    잔고      GET  /uapi/overseas-stock/v1/trading/inquire-balance      VTTS3012R
    매수가능  GET  /uapi/overseas-stock/v1/trading/inquire-psamount     VTTS3007R
    미체결    GET  /uapi/overseas-stock/v1/trading/inquire-nccs         VTTS3018R

★★ 모의투자는 **ORD_DVSN 00(지정가)만** 받는다. 실전(TTTT1002U/TTTT1006U)에만
   34(LOC)·32(LOO)·31(MOO)·33(MOC) 이 있다 - 공식 예제 원문에
   "모의투자 VTTT1002U(미국 매수 주문)로는 00:지정가만 가능" 이라고 박혀 있다.
   그래서 이 클라이언트는 LOC 를 **흉내 내지 않는다**. 지정가로 낸다는 사실을
   호출부가 알고 쓰도록 `ord_dvsn` 기본값을 "00" 으로 고정하고, 그 외 값을 주면
   거절한다 - 조용히 다른 주문이 나가는 것보다 시끄럽게 막는 게 낫다.
"""
from __future__ import annotations

from .kisVtsClient import BASE_URL, KisVtsClient, KisVtsError, _call, _request

PATH_ORDER = "/uapi/overseas-stock/v1/trading/order"
PATH_BALANCE = "/uapi/overseas-stock/v1/trading/inquire-balance"
PATH_PSAMOUNT = "/uapi/overseas-stock/v1/trading/inquire-psamount"
PATH_NCCS = "/uapi/overseas-stock/v1/trading/inquire-nccs"

TR_BUY = "VTTT1002U"
TR_SELL = "VTTT1001U"
TR_BALANCE = "VTTS3012R"
TR_PSAMOUNT = "VTTS3007R"
TR_NCCS = "VTTS3018R"

# 모의투자가 받는 유일한 주문구분. 실전의 LOC(34)는 여기 없다 - 위 모듈 docstring 참고.
ORD_DVSN_LIMIT = "00"
EXCHANGE = "NASD"   # 나스닥. TQQQ·SOXL 둘 다 나스닥 상장이다.


def _f(x, default=0.0):
    try:
        return float(str(x).strip() or default)
    except (TypeError, ValueError):
        return default


def _i(x, default=0):
    try:
        return int(float(str(x).strip() or default))
    except (TypeError, ValueError):
        return default


class KisVtsOverseasClient:
    """모의투자 해외주식. 인증·계좌는 KisVtsClient 것을 그대로 쓴다."""

    def __init__(self, base: KisVtsClient | None = None):
        self._base = base or KisVtsClient()

    @property
    def cano(self) -> str:
        return self._base.cano

    @property
    def acnt_prdt_cd(self) -> str:
        return self._base.acnt_prdt_cd

    def _headers(self, tr_id: str) -> dict:
        return self._base._headers(tr_id)

    def _acct(self) -> dict:
        return {"CANO": self.cano, "ACNT_PRDT_CD": self.acnt_prdt_cd}

    # ------------------------------------------------------------------ 조회

    def buying_power(self, symbol: str, price: float) -> dict:
        """주문가능 외화금액. 지정가를 넣어야 KIS 가 수량을 같이 계산해 준다."""
        _, body = _call("GET", BASE_URL + PATH_PSAMOUNT, f"매수가능금액({symbol})",
                        headers=self._headers(TR_PSAMOUNT),
                        params={**self._acct(), "OVRS_EXCG_CD": EXCHANGE,
                                "OVRS_ORD_UNPR": f"{price:.2f}", "ITEM_CD": symbol},
                        timeout=20)
        o = body.get("output") or {}
        return {
            "currency": (o.get("tr_crcy_cd") or "").strip(),
            "orderableCash": _f(o.get("ord_psbl_frcr_amt")),
            "orderableQty": _i(o.get("max_ord_psbl_qty")),
            "fxRate": _f(o.get("exrt")),
        }

    def holdings(self) -> list[dict]:
        """보유 종목. 연속조회를 끝까지 따라간다 - 잘린 목록을 전부인 척 쓰지 않는다."""
        rows, fk, nk, tr_cont = [], "", "", ""
        for _ in range(20):
            headers = self._headers(TR_BALANCE)
            if tr_cont in ("M", "F"):
                headers["tr_cont"] = "N"
            r, body = _call("GET", BASE_URL + PATH_BALANCE, "해외잔고",
                            headers=headers,
                            params={**self._acct(), "OVRS_EXCG_CD": EXCHANGE,
                                    "TR_CRCY_CD": "USD",
                                    "CTX_AREA_FK200": fk, "CTX_AREA_NK200": nk},
                            timeout=20)
            out = body.get("output1") or []
            if isinstance(out, dict):
                out = [out]
            for row in out:
                qty = _i(row.get("ovrs_cblc_qty"))
                if qty <= 0:
                    continue
                rows.append({
                    "symbol": (row.get("ovrs_pdno") or "").strip(),
                    "qty": qty,
                    "avgPrice": _f(row.get("pchs_avg_pric")),
                    "lastPrice": _f(row.get("now_pric2")),
                })
            tr_cont = (r.headers.get("tr_cont") or "").strip()
            if tr_cont not in ("M", "F"):
                break
            fk = body.get("ctx_area_fk200") or ""
            nk = body.get("ctx_area_nk200") or ""
        return rows

    def open_orders(self) -> list[dict]:
        """미체결. KRX 와 달리 미국 주문은 당일물이 아닐 수 있어 반드시 확인한다."""
        _, body = _call("GET", BASE_URL + PATH_NCCS, "미체결조회",
                        headers=self._headers(TR_NCCS),
                        params={**self._acct(), "OVRS_EXCG_CD": EXCHANGE,
                                "SORT_SQN": "DS",
                                "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""},
                        timeout=20)
        out = body.get("output") or []
        if isinstance(out, dict):
            out = [out]
        return [{
            "orderNo": (x.get("odno") or "").strip(),
            "symbol": (x.get("pdno") or "").strip(),
            "side": "SELL" if (x.get("sll_buy_dvsn_cd") or "") == "01" else "BUY",
            "qty": _i(x.get("ft_ord_qty")),
            "filledQty": _i(x.get("ft_ccld_qty")),
            "price": _f(x.get("ft_ord_unpr3")),
        } for x in out]

    # ------------------------------------------------------------------ 주문

    def place(self, side: str, symbol: str, qty: int, price: float,
              ord_dvsn: str = ORD_DVSN_LIMIT, dry_run: bool = True) -> dict:
        """미국 주식 주문. **기본이 dry_run 이다** - 실제 접수는 호출부가 명시해야 한다.

        모의투자는 지정가만 받으므로 `ord_dvsn` 은 "00" 외의 값을 거절한다.
        주문은 재시도하지 않는다(모듈 docstring).
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side 는 BUY|SELL: {side}")
        if ord_dvsn != ORD_DVSN_LIMIT:
            raise ValueError(
                f"모의투자는 지정가(00)만 받는다. LOC(34)는 실전 전용이다: {ord_dvsn}")
        if qty <= 0:
            raise ValueError(f"수량이 0 이하다: {qty}")
        if price <= 0:
            raise ValueError(f"지정가가 0 이하다: {price}")

        payload = {
            **self._acct(),
            "OVRS_EXCG_CD": EXCHANGE,
            "PDNO": symbol,
            "ORD_QTY": str(int(qty)),
            "OVRS_ORD_UNPR": f"{price:.2f}",
            "ORD_SVR_DVSN_CD": "0",
            "ORD_DVSN": ord_dvsn,
        }
        if dry_run:
            return {"dryRun": True, "side": side, "symbol": symbol,
                    "qty": int(qty), "price": round(price, 2), "payload": payload}

        import json as _json

        tr_id = TR_BUY if side == "BUY" else TR_SELL
        r = _request("POST", BASE_URL + PATH_ORDER, headers=self._headers(tr_id),
                     data=_json.dumps(payload), timeout=20)
        body = r.json()
        if r.status_code != 200 or body.get("rt_cd") != "0":
            raise KisVtsError(
                f"주문 실패({side} {symbol} {qty}@{price:.2f}): "
                f"{body.get('msg_cd')} {body.get('msg1')}")
        out = body.get("output") or {}
        return {
            "dryRun": False, "side": side, "symbol": symbol,
            "qty": int(qty), "price": round(price, 2),
            "orderNo": (out.get("ODNO") or "").strip(),
            "orderTime": (out.get("ORD_TMD") or "").strip(),
        }


def selftest() -> int:
    """네트워크 없이 도는 계약 검사. 조용히 틀릴 수 있는 것만 본다."""
    fails: list[str] = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    class _Stub(KisVtsOverseasClient):
        def __init__(self):
            pass
        cano = "12345678"
        acnt_prdt_cd = "01"

        def _headers(self, tr_id):
            return {"tr_id": tr_id}

        def _acct(self):
            return {"CANO": self.cano, "ACNT_PRDT_CD": self.acnt_prdt_cd}

    c = _Stub()

    ck("주문 TR_ID 가 모의투자 전용(V 로 시작)", TR_BUY.startswith("V") and TR_SELL.startswith("V"))
    ck("BASE_URL 이 모의투자 도메인", "openapivts" in BASE_URL)
    # 바늘을 조각에서 합친다 - 통짜로 쓰면 이 검사 줄 자체가 바늘이라 영원히 실패한다
    # (실제로 그렇게 짰다가 걸렸다. 교훈72 의 거울상 - 검사가 자기 자신을 잡았다).
    live_domain = "".join(("openapi.", "koreainvestment.com"))
    ck("이 파일에 실전 도메인 문자열이 없다",
       live_domain not in open(__file__, encoding="utf-8").read())

    d = c.place("BUY", "TQQQ", 3, 71.6)
    ck("기본이 dry_run", d["dryRun"] is True)
    ck("dry_run 이 페이로드를 그대로 보여준다", d["payload"]["ORD_DVSN"] == "00")
    ck("지정가가 소수 2자리 문자열", d["payload"]["OVRS_ORD_UNPR"] == "71.60")

    for bad, why in (("34", "LOC"), ("31", "MOO"), ("01", "시장가")):
        try:
            c.place("BUY", "TQQQ", 1, 10.0, ord_dvsn=bad)
            ck(f"{why}({bad}) 를 거절한다", False)
        except ValueError:
            ck(f"{why}({bad}) 를 거절한다", True)

    for args, why in ((("HOLD", "TQQQ", 1, 10.0), "잘못된 side"),
                      (("BUY", "TQQQ", 0, 10.0), "수량 0"),
                      (("BUY", "TQQQ", 1, 0.0), "지정가 0")):
        try:
            c.place(*args)
            ck(f"{why} 를 거절한다", False)
        except ValueError:
            ck(f"{why} 를 거절한다", True)

    ck("빈 문자열 파싱이 0 으로 떨어진다", _f("") == 0.0 and _i("") == 0)
    ck("숫자 문자열 파싱", _f("100000.00") == 100000.0 and _i("1382") == 1382)

    total = 14
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(selftest())
