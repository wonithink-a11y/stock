#!/usr/bin/env python3
"""A1 3차 정찰 — 폐지법인 소스 확보 (수집 아님, 판정만)

2차 정찰에서 KIND 상장법인목록(F)은 확보됐으나 상장폐지 목록(G)은 파라미터가
전혀 반영되지 않는 셸 페이지였다. 폐지목록은 생존편향 제거의 전부라 이것 없이
A1을 진행하면 백테스트가 '살아남은 기업만의 역사'가 된다.

세 경로를 동시에 확인한다.
  P1  delcompany.do 본문에서 실제 데이터 엔드포인트를 역추출 (JS·form 조각)
  P2  corpList.do의 searchType/marketType 스윕 — 폐지법인 다운로드가 있는지
  P3  DART corpCode.xml 차집합 — 과거 상장 이력 법인의 규모 파악

출력: data/backfill/_probe-delisted.json  (API 키는 어디에도 기록하지 않는다)
"""
import io
import json
import os
import re
import sys
import time
import traceback
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd
import requests

OUT = "data/backfill/_probe-delisted.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
KIND = "https://kind.krx.co.kr"
CORP_URL = f"{KIND}/corpgeneral/corpList.do"
DEL_URL = f"{KIND}/investwarn/delcompany.do"
DART_KEY = os.environ.get("DART_API_KEY", "")

results = {}


def rec(name, **kw):
    results[name] = kw
    print(f"[{name}] " + "  ".join(f"{k}={str(v)[:80]}"
                                   for k, v in kw.items()
                                   if k in ("rows", "status", "bytes", "count", "verdict", "error")))


def probe(name, fn):
    t0 = time.time()
    try:
        fn(name)
    except Exception as e:  # noqa: BLE001
        rec(name, verdict="EXC", error=f"{type(e).__name__}: {e}",
            trace=traceback.format_exc()[-500:])
    print(f"    ({time.time() - t0:.1f}s)")


# ── P0. 티커 형태 분류 — 'Common Shares Only'의 근거 확보 ────────
def p_shape(name):
    """끝자리 휴리스틱(우선주=끝자리≠0)은 영숫자 코드에서 무효다. 규칙을 넣기 전에
    그 규칙이 정상 데이터를 오탐하는지부터 본다(교훈1·26). 형태별로 세고 원자료를 남긴다."""
    r = requests.get(CORP_URL, params={"method": "download", "searchType": "13"},
                     timeout=(10, 40), headers={"User-Agent": UA})
    df = pd.read_html(io.StringIO(r.content.decode("euc-kr", "replace")))[0]
    df["종목코드"] = df["종목코드"].astype(str).str.strip().str.zfill(6)

    def shape(c):
        if re.fullmatch(r"\d{6}", c):
            return "digit6_last0" if c.endswith("0") else "digit6_lastNon0"
        if re.fullmatch(r"[0-9A-Z]{6}", c):
            return "alnum6"
        return "other"

    df["_shape"] = df["종목코드"].map(shape)
    counts = {k: int(v) for k, v in df["_shape"].value_counts().items()}

    odd = df[df["_shape"] != "digit6_last0"]
    cols = [c for c in ("회사명", "시장구분", "종목코드", "상장일", "업종") if c in df.columns]
    # 중복 코드는 자동 병합하지 않는다 — 사람이 판정할 대상이므로 전건을 남긴다
    dup_codes = df["종목코드"][df["종목코드"].duplicated(keep=False)]
    dups = df[df["종목코드"].isin(set(dup_codes))].sort_values("종목코드")

    rec(name, status=r.status_code, rows=len(df), shapeCounts=counts,
        oddSample=odd[cols].head(40).astype(str).to_dict("records"),
        oddCount=len(odd),
        dupCount=int(len(dups)),
        dupRows=dups[cols].astype(str).to_dict("records"))


# ── P1. delcompany.do 본문에서 실제 엔드포인트 역추출 ────────────
def p_reverse(name):
    """셸 페이지의 JS·form이 진짜 데이터 URL을 알고 있다. 첫 1,200자(meta 태그)를
    보는 대신 패턴으로 추출한다 — 원문 위치를 모를 때 head 슬라이스는 무용지물이다."""
    r = requests.get(DEL_URL, timeout=(10, 40), headers={"User-Agent": UA})
    body = r.text

    def uniq(pat, n=40, flags=0):
        seen, out = set(), []
        for m in re.findall(pat, body, flags):
            s = m if isinstance(m, str) else " | ".join(m)
            s = s.strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
            if len(out) >= n:
                break
        return out

    # searchDelCompany 가 등장하는 지점 주변 — 호출부가 여기에 있다
    ctx = []
    for m in re.finditer(r"searchDelCompany\w*", body):
        ctx.append(body[max(0, m.start() - 400):m.start() + 400])
        if len(ctx) >= 4:
            break

    rec(name, status=r.status_code, bytes=len(body),
        doUrls=uniq(r"""['"]([^'"]*\.do[^'"]*)['"]"""),
        formActions=uniq(r"""<form[^>]*action\s*=\s*['"]([^'"]+)['"]""", 10, re.I),
        hiddenInputs=uniq(r"""<input[^>]*type=['"]hidden['"][^>]*name=['"]([^'"]+)['"][^>]*value=['"]([^'"]*)['"]""", 40, re.I),
        methodLiterals=uniq(r"""method\s*[:=]\s*['"]([A-Za-z_]+)['"]""", 30),
        ajaxUrls=uniq(r"""url\s*:\s*['"]([^'"]+)['"]""", 20),
        searchDelContext=ctx)


# ── P2. corpList.do 스윕 — 폐지법인 다운로드가 있는가 ────────────
SWEEP = [
    {"method": "download", "searchType": "13"},                     # 기준(상장법인)
    {"method": "download", "searchType": "14"},
    {"method": "download", "searchType": "15"},
    {"method": "download", "searchType": "13", "marketType": "delMkt"},
    {"method": "download", "searchType": "13", "isurCd": "", "orderMode": "3"},
    {"method": "loadCorpList", "searchType": "13"},
]


def p_sweep(name, params):
    r = requests.get(CORP_URL, params=params, timeout=(10, 40),
                     headers={"User-Agent": UA})
    txt = r.content.decode("euc-kr", "replace")
    info = {"params": params, "status": r.status_code, "bytes": len(r.content)}
    try:
        df = pd.read_html(io.StringIO(txt))[0]
        info["rows"] = len(df)
        info["columns"] = [str(c) for c in df.columns]
        info["sample"] = df.head(2).astype(str).to_dict("records")
        # 폐지목록이라면 '폐지일' 계열 컬럼이 있어야 한다
        info["hasExitCol"] = any(re.search(r"폐지|말소|해지", c) for c in info["columns"])
    except Exception as e:  # noqa: BLE001
        info["error"] = str(e)[:150]
        info["head"] = txt[:300]
    rec(name, **info)


# ── P3. DART corpCode.xml 차집합 — 과거 상장 이력 법인 규모 ──────
def p_dart(name):
    if not DART_KEY:
        rec(name, verdict="NO_KEY")
        return
    r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                     params={"crtfc_key": DART_KEY}, timeout=(10, 90))
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(zf.read(zf.namelist()[0]).decode("utf-8"))
    with_code = {}
    total = 0
    for it in root.iter("list"):
        total += 1
        sc = (it.findtext("stock_code") or "").strip()
        if sc:
            with_code[sc] = (it.findtext("corp_name") or "").strip()

    # 현재 상장 집합과의 차집합 = 과거 상장 이력 후보
    cur = set()
    lr = requests.get(CORP_URL, params={"method": "download", "searchType": "13"},
                      timeout=(10, 40), headers={"User-Agent": UA})
    cdf = pd.read_html(io.StringIO(lr.content.decode("euc-kr", "replace")))[0]
    for c in cdf["종목코드"].astype(str):
        cur.add(c.zfill(6))

    gone = {k: v for k, v in with_code.items() if k.zfill(6) not in cur}
    rec(name, status=r.status_code, totalCorps=total,
        withStockCode=len(with_code), currentListed=len(cur),
        count=len(gone), sample=list(gone.items())[:15],
        # 영숫자 티커가 DART에도 있는지 — A2~A5 파서 전파 문제
        alnumTickers=[k for k in with_code if not k.isdigit()][:15])


def main():
    print("A1 3차 정찰 — 폐지법인 소스 + 티커 형태\n")
    probe("P0_ticker_shape", p_shape)
    probe("P1_reverse_delcompany", p_reverse)
    for i, p in enumerate(SWEEP, 1):
        probe(f"P2_{i}_sweep", lambda n, pp=p: p_sweep(n, pp))
    probe("P3_dart_diff", p_dart)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"probedAt": time.strftime("%Y-%m-%dT%H:%M:%S+0900"),
                   "results": results}, f, ensure_ascii=False, indent=2)

    print("\n── 요약 ──")
    p1 = results.get("P1_reverse_delcompany", {})
    print(f"  P1 .do URL 후보 {len(p1.get('doUrls', []))}개 / "
          f"method 리터럴 {len(p1.get('methodLiterals', []))}개")
    for k, v in results.items():
        if k.startswith("P2"):
            print(f"  {k}: rows={v.get('rows')} exitCol={v.get('hasExitCol')} "
                  f"params={v.get('params')}")
    p0 = results.get("P0_ticker_shape", {})
    print(f"  P0 형태분포 {p0.get('shapeCounts')}  비표준 {p0.get('oddCount')}건  "
          f"중복행 {p0.get('dupCount')}건")
    p3 = results.get("P3_dart_diff", {})
    print(f"  P3 DART stock_code {p3.get('withStockCode')} − 현재상장 "
          f"{p3.get('currentListed')} = 과거이력 후보 {p3.get('count')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
