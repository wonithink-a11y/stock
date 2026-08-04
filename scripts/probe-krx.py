#!/usr/bin/env python3
"""A1 정찰 — KRX/KIND 경로 가용성 판정 (수집 아님, 판정만)

A1이 400 LOGOUT으로 막혔다. 같은 호스트인데 A0.5의 개별종목 시계열은 성공했으므로
'IP 차단'인지 '세션 요구'인지 '로그인 실패'인지를 먼저 갈라야 한다.
148개월 루프를 다시 돌리지 않고 7개 경로를 1회씩만 확인한다(교훈32).

출력: data/backfill/_probe-krx.json  (원문 head 포함. 다음 라운드의 유일한 입력)
비밀번호는 어디에도 기록하지 않는다.
"""
import json
import os
import sys
import time
import traceback

import requests

OUT = "data/backfill/_probe-krx.json"
TRD = "20260803"          # A0.5 캘린더의 마지막 거래일
OLD = "20140513"          # 캘린더 첫 거래일
JSON_URL = "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd"
SEED_URL = ("https://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd"
            "?menuId=MDC0201020101")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

results = {}


def rec(name, **kw):
    results[name] = kw
    verdict = kw.get("verdict", "?")
    print(f"[{name}] {verdict}  " + "  ".join(
        f"{k}={v}" for k, v in kw.items() if k in ("status", "bytes", "rows", "error")))
    head = kw.get("head")
    if head:
        print(f"    head: {head[:300]}")


def body_verdict(r):
    t = (r.text or "").strip()
    if t.upper().startswith("LOGOUT"):
        return "LOGOUT"
    if t.startswith("{") or t.startswith("["):
        return "JSON"
    if "<html" in t[:200].lower():
        return "HTML"
    return "OTHER"


def probe(name, fn):
    t0 = time.time()
    try:
        fn(name)
    except Exception as e:  # noqa: BLE001
        rec(name, verdict="EXC", error=f"{type(e).__name__}: {e}",
            trace=traceback.format_exc()[-800:])
    print(f"    ({time.time() - t0:.1f}s)")


# ── A. 세션 없이 raw POST ──────────────────────────────────────
def bulk_payload(trd, mkt="STK"):
    return {"bld": "dbms/MDC/STAT/standard/MDCSTAT01501",
            "locale": "ko_KR", "mktId": mkt, "trdDd": trd,
            "share": "1", "money": "1", "csvxls_isNo": "false"}


def p_raw(name):
    r = requests.post(JSON_URL, data=bulk_payload(TRD), timeout=(10, 20),
                      headers={"User-Agent": UA})
    rec(name, verdict=body_verdict(r), status=r.status_code,
        bytes=len(r.content), head=(r.text or "")[:400])


# ── B. 세션 시드 후 POST (Referer 포함) ─────────────────────────
def p_seeded(name):
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    g = s.get(SEED_URL, timeout=(10, 20))
    r = s.post(JSON_URL, data=bulk_payload(TRD), timeout=(10, 20),
               headers={"Referer": SEED_URL,
                        "X-Requested-With": "XMLHttpRequest"})
    rec(name, verdict=body_verdict(r), status=r.status_code,
        seedStatus=g.status_code, cookies=sorted(s.cookies.keys()),
        bytes=len(r.content), head=(r.text or "")[:400])


# ── C. A0.5가 성공한 경로 (개별종목 시계열) ─────────────────────
def p_single(name):
    from pykrx import stock
    df = stock.get_market_ohlcv_by_date(TRD, TRD, "005930")
    rec(name, verdict="OK" if df is not None and not df.empty else "EMPTY",
        rows=(0 if df is None else len(df)),
        cols=(None if df is None else [str(c) for c in df.columns]))


# ── D. pykrx 전종목 (A1이 쓰는 경로) ────────────────────────────
def p_bulk_pykrx(name):
    from pykrx import stock
    df = stock.get_market_ohlcv(TRD, market="KOSPI")
    rec(name, verdict="OK" if df is not None and not df.empty else "EMPTY",
        rows=(0 if df is None else len(df)))


# ── E. pykrx 로그인 상태 ────────────────────────────────────────
def p_login(name):
    has = bool(os.environ.get("KRX_ID")) and bool(os.environ.get("KRX_PW"))
    mods = []
    try:
        import pykrx
        mods.append(getattr(pykrx, "__version__", "unknown"))
    except Exception:  # noqa: BLE001
        pass
    # pykrx 버전별로 로그인 모듈 경로가 다르다. 있는 것만 찾아 호출 결과를 본다.
    found, called = None, None
    for path, fname in (("pykrx.website.krx.krxio", "login"),
                        ("pykrx.website.comm.webio", "login"),
                        ("pykrx.website.krx.market.core", "login")):
        try:
            m = __import__(path, fromlist=["*"])
            if hasattr(m, fname):
                found = f"{path}.{fname}"
                break
        except Exception:  # noqa: BLE001
            continue
    rec(name, verdict="CRED_OK" if has else "CRED_MISSING",
        pykrxVersion=mods, loginEntrypoint=found, loginCalled=called)


# ── F. KIND 상장법인목록 ────────────────────────────────────────
def p_kind_list(name):
    url = "https://kind.krx.co.kr/corpgeneral/corpList.do"
    r = requests.get(url, params={"method": "download", "searchType": "13"},
                     timeout=(10, 30), headers={"User-Agent": UA})
    txt = r.content.decode("euc-kr", "replace")
    rows = txt.count("<tr")
    rec(name, verdict="OK" if rows > 100 else body_verdict(r),
        status=r.status_code, bytes=len(r.content), rows=rows,
        head=txt[:400])


# ── G. KIND 상장폐지법인 (§4.4 원래 정찰 대상) ──────────────────
def p_kind_del(name):
    url = "https://kind.krx.co.kr/investwarn/delcompany.do"
    payload = {"method": "searchDelCompanyMain", "currentPageSize": "3000",
               "pageIndex": "1", "forward": "delcompany_down",
               "searchCodeType": "", "repIsuSrtCd": "", "searchCorpName": "",
               "orderMode": "1", "orderStat": "D"}
    r = requests.post(url, data=payload, timeout=(10, 30),
                      headers={"User-Agent": UA})
    txt = r.text
    tables = 0
    try:
        import io as _io
        import pandas as pd
        tables = len(pd.read_html(_io.StringIO(txt)))
    except Exception as e:  # noqa: BLE001
        rec(name, verdict="PARSE_FAIL", status=r.status_code,
            bytes=len(txt), error=str(e)[:200], head=txt[:1500])
        return
    rec(name, verdict="OK" if tables else "NO_TABLE", status=r.status_code,
        bytes=len(txt), tables=tables, head=txt[:600])


def main():
    print("A1 정찰 — KRX/KIND 경로 가용성\n")
    probe("E_login_state", p_login)
    probe("C_single_ohlcv_A05path", p_single)
    probe("A_bulk_raw_nosession", p_raw)
    probe("B_bulk_seeded_session", p_seeded)
    probe("D_bulk_pykrx", p_bulk_pykrx)
    probe("F_kind_corplist", p_kind_list)
    probe("G_kind_delisted", p_kind_del)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"probedAt": time.strftime("%Y-%m-%dT%H:%M:%S+0900"),
                   "tradeDate": TRD, "results": results},
                  f, ensure_ascii=False, indent=2)

    v = {k: r.get("verdict") for k, r in results.items()}
    print("\n── 판정 ──")
    for k, s in v.items():
        print(f"  {k:26s} {s}")

    single_ok = v.get("C_single_ohlcv_A05path") == "OK"
    bulk_ok = any(v.get(k) in ("JSON", "OK") for k in
                  ("A_bulk_raw_nosession", "B_bulk_seeded_session", "D_bulk_pykrx"))
    kind_ok = v.get("F_kind_corplist") == "OK"

    print("\n── 결론 ──")
    if bulk_ok:
        print("  H2 확정 — bulk 조회 가능. 성공한 경로로 A1을 고친다.")
    elif single_ok and kind_ok:
        print("  H3 확정 — bulk 영구 차단. KIND 목록 + 개별종목 일봉으로 A1 재설계.")
    elif single_ok:
        print("  H3-부분 — 개별종목만 가능, KIND도 막힘. 유니버스 소스 재검토 필요.")
    else:
        print("  KRX 전면 차단 — A0.5도 재현 불가. IP/계정 문제.")
    # 정찰은 판정이 산출물이다. 어떤 결과든 exit 0으로 끝내 산출물을 커밋시킨다.
    return 0


if __name__ == "__main__":
    sys.exit(main())
