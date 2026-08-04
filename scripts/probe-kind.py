#!/usr/bin/env python3
"""A1 2차 정찰 — KIND 목록의 실제 구조 확정 (수집 아님, 판정만)

1차 정찰에서 KRX bulk는 영구 차단, KIND는 가용으로 판정됐다(H3).
그러나 폐지법인 응답이 77KB/테이블1개라 '전건 확보'인지 '1페이지만'인지 알 수 없다.
목록이 잘린 채 A1을 다시 쓰면 생존편향이 조용히 남는다 — 되돌리기 어려운 실패다.

확정 대상: 컬럼명 / 실제 행 수 / 페이지네이션 / 시장 구분 / 우선주 포함 / 연도 커버리지
출력: data/backfill/_probe-kind.json
"""
import io
import json
import os
import re
import sys
import time
import traceback

import pandas as pd
import requests

OUT = "data/backfill/_probe-kind.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CORP_URL = "https://kind.krx.co.kr/corpgeneral/corpList.do"
DEL_URL = "https://kind.krx.co.kr/investwarn/delcompany.do"

results = {}


def summarize(df, name, note=None):
    """컬럼·행수·표본만. 원자료를 통째로 남기지 않는다(진단 파일이 데이터가 되면 안 된다)."""
    cols = [str(c) for c in df.columns]
    out = {"rows": len(df), "columns": cols,
           "sample": df.head(3).astype(str).to_dict("records")}
    # 날짜형 컬럼이 있으면 연도 커버리지를 본다 — 초기 연도가 비면 생존편향이 남는다
    for c in cols:
        if re.search(r"일자|일$|날짜", c):
            yrs = df[c].astype(str).str.extract(r"(\d{4})")[0].dropna()
            if len(yrs):
                vc = yrs.value_counts().sort_index()
                out["yearCoverage"] = {str(k): int(v) for k, v in vc.items()}
                out["yearRange"] = [str(vc.index[0]), str(vc.index[-1])]
            break
    if note:
        out["note"] = note
    return out


def rec(name, **kw):
    results[name] = kw
    print(f"[{name}] rows={kw.get('rows')} cols={kw.get('columns')}")
    if kw.get("yearRange"):
        print(f"    연도 {kw['yearRange']}  (건수 {len(kw.get('yearCoverage', {}))}개 연도)")
    if kw.get("error"):
        print(f"    ! {kw['error'][:200]}")


def probe(name, fn):
    t0 = time.time()
    try:
        fn(name)
    except Exception as e:  # noqa: BLE001
        rec(name, error=f"{type(e).__name__}: {e}",
            trace=traceback.format_exc()[-600:])
    print(f"    ({time.time() - t0:.1f}s)")


# ── F. 상장법인목록: 시장별 분리 + 상장일·우선주 확인 ───────────
def corp_list(market_type):
    params = {"method": "download"}
    if market_type:
        params["marketType"] = market_type
    r = requests.get(CORP_URL, params=params, timeout=(10, 40),
                     headers={"User-Agent": UA})
    txt = r.content.decode("euc-kr", "replace")
    df = pd.read_html(io.StringIO(txt))[0]
    if "종목코드" in df.columns:
        df["종목코드"] = df["종목코드"].astype(str).str.zfill(6)
    return df, r.status_code


def p_corp(name, market_type):
    df, st = corp_list(market_type)
    s = summarize(df, name)
    s["status"] = st
    s["marketType"] = market_type or "(전체)"
    if "종목코드" in df.columns:
        codes = df["종목코드"]
        # 우선주는 코드 끝자리가 0이 아니다(005935 등). 포함 여부가 유니버스 정의를 가른다.
        s["nonCommonCodeCount"] = int((~codes.str.endswith("0")).sum())
        s["nonCommonSample"] = codes[~codes.str.endswith("0")].head(5).tolist()
        s["dupCodes"] = int(codes.duplicated().sum())
    rec(name, **s)


# ── G. 상장폐지법인: 페이지네이션 변형 매트릭스 ─────────────────
DEL_VARIANTS = {
    "G1_pageSize3000": {"method": "searchDelCompanyMain", "currentPageSize": "3000",
                        "pageIndex": "1", "forward": "delcompany_down",
                        "searchCodeType": "", "repIsuSrtCd": "",
                        "searchCorpName": "", "orderMode": "1", "orderStat": "D"},
    "G2_pageSize100":  {"method": "searchDelCompanyMain", "currentPageSize": "100",
                        "pageIndex": "1", "orderMode": "1", "orderStat": "D"},
    "G3_page2":        {"method": "searchDelCompanyMain", "currentPageSize": "100",
                        "pageIndex": "2", "orderMode": "1", "orderStat": "D"},
    "G4_dateRange":    {"method": "searchDelCompanyMain", "currentPageSize": "3000",
                        "pageIndex": "1", "fromDate": "2014-01-01",
                        "toDate": "2026-08-04", "orderMode": "1", "orderStat": "D"},
    "G5_bare":         {"method": "searchDelCompanyMain"},
}


def p_del(name, payload):
    r = requests.post(DEL_URL, data=payload, timeout=(10, 40),
                      headers={"User-Agent": UA,
                               "X-Requested-With": "XMLHttpRequest"})
    txt = r.text
    tables = pd.read_html(io.StringIO(txt))
    # 종목코드·사유가 함께 있는 표가 데이터 표다. 레이아웃 표를 데이터로 오인하지 않는다.
    best, why = None, []
    for i, df in enumerate(tables):
        cols = [str(c) for c in df.columns]
        why.append({"idx": i, "rows": len(df), "columns": cols})
        if any(re.search(r"종목코드|단축코드", c) for c in cols) and len(df) > 1:
            best = df
            break
    if best is None:
        rec(name, status=r.status_code, bytes=len(txt), tableCount=len(tables),
            tables=why, error="종목코드 컬럼을 가진 표 없음", head=txt[:1200])
        return
    s = summarize(best, name)
    s["status"] = r.status_code
    s["bytes"] = len(txt)
    s["tableCount"] = len(tables)
    # 총건수 표기가 페이지에 있으면 잘림 여부를 바로 판정할 수 있다
    m = re.search(r"총\s*<?[^>]*>?\s*([\d,]+)\s*건", txt)
    s["totalCountOnPage"] = m.group(1) if m else None
    rec(name, **s)


def main():
    print("A1 2차 정찰 — KIND 목록 구조 확정\n")
    probe("F0_corp_all", lambda n: p_corp(n, None))
    probe("F1_corp_kospi", lambda n: p_corp(n, "stockMkt"))
    probe("F2_corp_kosdaq", lambda n: p_corp(n, "kosdaqMkt"))
    for k, v in DEL_VARIANTS.items():
        probe(k, lambda n, p=v: p_del(n, p))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"probedAt": time.strftime("%Y-%m-%dT%H:%M:%S+0900"),
                   "results": results}, f, ensure_ascii=False, indent=2)

    print("\n── 요약 ──")
    for k, v in results.items():
        print(f"  {k:20s} rows={str(v.get('rows')):>6s}  "
              f"yr={v.get('yearRange')}  err={str(v.get('error'))[:40]}")

    dels = [v.get("rows") or 0 for k, v in results.items() if k.startswith("G")]
    print("\n── 결론 ──")
    if max(dels or [0]) >= 500:
        print(f"  폐지목록 전건 확보 가능 (최대 {max(dels)}행) — A1 재설계 착수 가능")
    elif max(dels or [0]) > 0:
        print(f"  ⚠ 폐지목록 최대 {max(dels)}행 — 페이지네이션 루프 필요. "
              "1페이지만 쓰면 생존편향이 남는다")
    else:
        print("  ⚠ 폐지목록 파싱 실패 — head 원문으로 파서 재작성 필요")
    return 0


if __name__ == "__main__":
    sys.exit(main())
