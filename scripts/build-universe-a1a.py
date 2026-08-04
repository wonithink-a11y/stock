#!/usr/bin/env python3
"""A1a — 현재 상장 유니버스 (BF-1.1)

KIND 상장법인목록에서 KOSPI·KOSDAQ 보통주 유니버스를 확정하고 corp_code를 매핑한다.
정의는 config/policies/universe.v1.json(UN-1.0)이 단일 산출점이다 — 이 스크립트에
시장·SPAC·중복 규칙을 하드코딩하지 않는다.

입력: config/policies/universe.v1.json
출력:
  data/backfill/universe/a1a/current.jsonl   유니버스 (사실)
  data/backfill/universe/a1a/_diagnostics.json

BF-1.0의 '월별 전종목 스냅샷' 방식은 폐기했다 — KRX bulk 조회가 Actions에서
영구 차단됐다(BF-1.1 §10). 폐지 이력은 A1b가 따로 담당한다.
"""
import io
import json
import os
import re
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

import pandas as pd
import requests

POLICY = "config/policies/universe.v1.json"
OUT_DIR = "data/backfill/universe/a1a"
CACHE_CORP = "data/cache/corpCodeMap.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DART_KEY = os.environ.get("DART_API_KEY", "")
STAGE_VERSION = "A1a.0"

fails, warns = [], []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


# ── 네트워크 가드 ──────────────────────────────────────────────
# 외부 라이브러리의 기본 timeout이 None이면 재시도 로직이 지연 증폭기가 된다(교훈31).
_orig_send = requests.adapters.HTTPAdapter.send


def _send(self, request, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = (10, 40)
    return _orig_send(self, request, **kw)


requests.adapters.HTTPAdapter.send = _send


def _retry(fn, what, attempts=3):
    """빈 결과도 실패로 본다. 조회 실패를 성공으로 위장하면 종목이 조용히 사라진다."""
    last = None
    for i in range(attempts):
        try:
            r = fn()
            empty = r is None or (hasattr(r, "empty") and r.empty) or \
                    (isinstance(r, (list, dict)) and len(r) == 0)
            if empty:
                last = ValueError("빈 응답")
            else:
                return r
        except Exception as e:  # noqa: BLE001
            last = e
        if i < attempts - 1:
            time.sleep(2 ** i)
    print(f"  ! {what} 실패: {type(last).__name__}: {last}")
    return None


# ── 식별자 정규화 (BF-1.1 §1.1) ────────────────────────────────
def normalize_ticker(raw, pattern):
    """길이 보정만 한다. 비숫자 제거는 하지 않는다 — 0218L0 → 02180 파괴를 막는 유일한 지점.
    실패는 예외로 올린다. 조용히 버리면 종목이 사라진 것을 아무도 모른다."""
    s = str(raw).strip().upper().zfill(6)
    if not re.fullmatch(pattern, s):
        raise ValueError(f"ticker 계약 위반: {raw!r} → {s!r}")
    return s


# ── 1. 소스 수집 ───────────────────────────────────────────────
def fetch_corp_list(src):
    r = _retry(lambda: requests.get(src["url"], params=src["params"],
                                    headers={"User-Agent": UA}),
               "KIND 상장법인목록")
    if r is None or r.status_code != 200:
        print("KIND 상장법인목록 수신 실패 — 중단")
        sys.exit(2)
    txt = r.content.decode(src["encoding"], "replace")
    return pd.read_html(io.StringIO(txt))[0], len(r.content)


# ── 2. corp_code 매핑 ──────────────────────────────────────────
def load_corp_map():
    if os.path.exists(CACHE_CORP):
        try:
            with open(CACHE_CORP, encoding="utf-8") as f:
                c = json.load(f)
            if isinstance(c, dict) and c.get("map"):
                print(f"  corpCodeMap 캐시 사용 ({len(c['map'])}건)")
                return c["map"]
        except Exception as e:  # noqa: BLE001
            print(f"  캐시 무시: {e}")

    if not DART_KEY:
        print("  ! DART_API_KEY 없음 — corp_code 매핑 생략")
        return {}

    r = _retry(lambda: requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                                    params={"crtfc_key": DART_KEY}, timeout=(10, 90)),
               "corpCode.xml")
    if r is None or r.status_code != 200:
        return {}
    try:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(zf.read(zf.namelist()[0]).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"  ! corpCode.xml 파싱 실패: {e}")
        return {}

    m = {}
    for it in root.iter("list"):
        sc = (it.findtext("stock_code") or "").strip().upper()
        cc = (it.findtext("corp_code") or "").strip()
        if sc and cc:
            m[sc.zfill(6)] = cc
    os.makedirs(os.path.dirname(CACHE_CORP), exist_ok=True)
    with open(CACHE_CORP, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"fetchedAt": time.strftime("%Y-%m-%d"), "map": m},
                  f, ensure_ascii=False, sort_keys=True)
    print(f"  corpCodeMap 신규 수집 ({len(m)}건)")
    return m


# ── 3. 필터 파이프라인 ─────────────────────────────────────────
def build(df, pol, corp_map, diag):
    src = pol["source"]
    mmap = src["marketMap"]
    pat = pol["tickerPattern"]

    # 3-1 정규화
    bad = []
    rows = []
    for _, r in df.iterrows():
        try:
            t = normalize_ticker(r["종목코드"], pat)
        except ValueError as e:
            bad.append(str(e))
            continue
        rows.append({
            "ticker": t,
            "name": str(r["회사명"]).strip(),
            "market": mmap.get(str(r["시장구분"]).strip(), str(r["시장구분"]).strip()),
            "listedAt": str(r["상장일"]).strip(),
            "sector": str(r["업종"]).strip() if pd.notna(r.get("업종")) else None,
            "fiscalMonth": str(r["결산월"]).strip() if pd.notna(r.get("결산월")) else None,
        })
    diag["tickerContractViolations"] = bad

    # 3-2 중복 — 전 필드 일치만 제거한다. 한 필드라도 다르면 회사 교체일 수 있으므로 FAIL.
    by_ticker = defaultdict(list)
    for x in rows:
        by_ticker[x["ticker"]].append(x)
    kept, exact_removed, partial = [], 0, []
    for t, group in by_ticker.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        uniq = {json.dumps(g, ensure_ascii=False, sort_keys=True) for g in group}
        if len(uniq) == 1:
            kept.append(group[0])
            exact_removed += len(group) - 1
        else:
            partial.append({"ticker": t, "rows": group})
            kept.extend(group)          # 제거하지 않는다 — 사람이 판정한다
    diag["exactDuplicateRemoved"] = exact_removed
    diag["partialDuplicates"] = partial

    # 3-3 시장 필터
    pre_market = Counter(x["market"] for x in kept)
    diag["marketCountsBeforeFilter"] = dict(pre_market)
    konex_excluded = [x for x in kept if x["market"] in pol["excludeMarkets"]]
    kept = [x for x in kept if x["market"] in pol["includeMarkets"]]
    diag["konexExcluded"] = len(konex_excluded)

    # 3-4 SPAC — 회사명만으로 판정한다. 업종은 교차 집계만.
    spac_re = re.compile(pol["spacNamePattern"])
    spacs = [x for x in kept if spac_re.search(x["name"])]
    if pol.get("excludeSpac"):
        kept = [x for x in kept if not spac_re.search(x["name"])]
    diag["spacExcluded"] = len(spacs)
    diag["spacSample"] = [{"ticker": s["ticker"], "name": s["name"],
                           "market": s["market"], "sector": s["sector"]}
                          for s in spacs[:20]]
    hint = set(pol.get("spacSectorHint") or [])
    diag["spacSectorCross"] = {
        "nameHitSectorHit": sum(1 for s in spacs if s["sector"] in hint),
        "nameHitSectorMiss": sum(1 for s in spacs if s["sector"] not in hint),
        "nameMissSectorHit": sum(1 for x in kept if x["sector"] in hint),
    }

    # 3-5 corp_code
    for x in kept:
        x["corp"] = corp_map.get(x["ticker"])

    # 스키마 키 순서 고정 (BF-1.1 §3 — JSON 키 순서는 스키마 정의 순서)
    order = ["ticker", "name", "market", "corp", "listedAt", "sector", "fiscalMonth"]
    kept = [{k: x.get(k) for k in order} for x in kept]
    kept.sort(key=lambda x: x["ticker"])
    return kept


# ── 4. 인수 조건 ───────────────────────────────────────────────
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate(uni, pol, diag, src_rows):
    a = pol["acceptance"]
    print("\n[인수 조건]")

    chk(a["sourceRowsMin"] <= src_rows <= a["sourceRowsMax"],
        f"소스 행 수 {src_rows} ∈ [{a['sourceRowsMin']}, {a['sourceRowsMax']}]")

    chk(not diag["tickerContractViolations"],
        f"ticker 계약 {pol['tickerPattern']} 전건 통과 "
        f"(위반 {len(diag['tickerContractViolations'])}건)")

    chk(len(diag["partialDuplicates"]) == a["partialDuplicate"],
        f"부분 일치 중복 {len(diag['partialDuplicates'])}건 (0이어야 함 — 회사 교체 가능성, 사람 판정)")

    codes = [x["ticker"] for x in uni]
    resid = len(codes) - len(set(codes))
    chk(resid == a["residualDuplicate"], f"잔여 ticker 중복 {resid}건")

    mc = Counter(x["market"] for x in uni)
    chk(mc.get("KOSPI", 0) >= a["kospiMin"], f"KOSPI {mc.get('KOSPI', 0)} >= {a['kospiMin']}")
    chk(mc.get("KOSDAQ", 0) >= a["kosdaqMin"], f"KOSDAQ {mc.get('KOSDAQ', 0)} >= {a['kosdaqMin']}")
    chk(mc.get("KONEX", 0) == a["konexAfterFilter"], f"KONEX 잔존 {mc.get('KONEX', 0)}건")

    # 제외 건수가 0이면 데이터가 아니라 필터 파손이다 — 스팩·코넥스는 상시 존재한다
    chk(diag["spacExcluded"] >= a["spacExcludedMin"],
        f"SPAC 제외 {diag['spacExcluded']}건 >= {a['spacExcludedMin']} (0이면 정규식 파손)")
    chk(diag["konexExcluded"] >= a["konexExcludedMin"],
        f"KONEX 제외 {diag['konexExcluded']}건 >= {a['konexExcludedMin']}")
    spac_re = re.compile(pol["spacNamePattern"])
    left = [x["ticker"] for x in uni if spac_re.search(x["name"])]
    chk(len(left) == a["spacAfterFilter"], f"SPAC 잔존 {len(left)}건")

    ok_date = [x for x in uni if DATE_RE.match(x["listedAt"] or "")]
    rate = len(ok_date) / len(uni) if uni else 0
    chk(rate >= a["listedAtParseRate"], f"상장일 파싱률 {rate*100:.2f}%")
    today = time.strftime("%Y-%m-%d")
    future = [x["ticker"] for x in uni if (x["listedAt"] or "") > today]
    chk(len(future) == a["futureListedAt"], f"미래 상장일 {len(future)}건")
    diag["futureListedAt"] = future

    miss = [x["ticker"] for x in uni if not x["corp"]]
    mrate = len(miss) / len(uni) if uni else 0
    warn(mrate < a["corpCodeMissingRateWarn"],
         f"corp_code 매핑 실패율 {mrate*100:.1f}% ({len(miss)}/{len(uni)})")
    diag["corpCodeMissing"] = miss[:500]

    # corp_code 유일성 — 첫 실행은 WARN. 실측 후 FAIL 승격한다(BF-1.1 §7 A1a).
    cc = [x["corp"] for x in uni if x["corp"]]
    cdup = len(cc) - len(set(cc))
    warn(cdup == 0, f"corp_code 유일성 (non-null 중 중복 {cdup}건) — 1 corp → N ticker 후보")
    if cdup:
        bag = defaultdict(list)
        for x in uni:
            if x["corp"]:
                bag[x["corp"]].append({"ticker": x["ticker"], "name": x["name"],
                                       "market": x["market"]})
        diag["corpCodeDuplicates"] = {k: v for k, v in bag.items() if len(v) > 1}


# ── 5. main ────────────────────────────────────────────────────
def main():
    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음 — UN-1.0 정책 파일이 필요하다")
        sys.exit(1)
    with open(POLICY, encoding="utf-8") as f:
        pol = json.load(f)
    print(f"유니버스 정책 {pol['version']} · 시장 {pol['includeMarkets']} · "
          f"SPAC제외={pol['excludeSpac']}")

    diag = {"stage": "A1a", "stageVersion": STAGE_VERSION,
            "universePolicy": pol["version"]}

    print("\n[1/3] KIND 상장법인목록")
    df, nbytes = fetch_corp_list(pol["source"])
    print(f"  {len(df)}행 / {nbytes}바이트")
    diag["sourceRows"] = len(df)
    diag["sourceBytes"] = nbytes

    print("\n[2/3] corp_code 매핑")
    corp_map = load_corp_map()

    print("\n[3/3] 필터 파이프라인")
    uni = build(df, pol, corp_map, diag)
    mc = Counter(x["market"] for x in uni)
    print(f"  최종 {len(uni)}종목  {dict(mc)}  "
          f"(중복제거 {diag['exactDuplicateRemoved']} · "
          f"KONEX -{diag['konexExcluded']} · SPAC -{diag['spacExcluded']})")

    diag["finalCount"] = len(uni)
    diag["marketCounts"] = dict(mc)
    diag["alnumTickers"] = sorted(x["ticker"] for x in uni if not x["ticker"].isdigit())

    validate(uni, pol, diag, len(df))

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/current.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for x in uni:
            f.write(json.dumps(x, ensure_ascii=False, sort_keys=False) + "\n")
    with open(f"{OUT_DIR}/_diagnostics.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2, sort_keys=False)

    print(f"\n{OUT_DIR}/current.jsonl — {len(uni)}종목 "
          f"(영숫자 티커 {len(diag['alnumTickers'])}건)")
    if warns:
        print(f"\nWARN {len(warns)}건 (실패 아님, 확인 필요):")
        for w in warns:
            print(f"  - {w}")
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패")
        sys.exit(1)


if __name__ == "__main__":
    main()
