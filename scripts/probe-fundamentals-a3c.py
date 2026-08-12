#!/usr/bin/env python3
"""A3c 정찰 — 주식의 총수 현황(stockTotqySttus)이 PIT 앵커를 주는가, 그리고
기중 주식수 변경(액면분할 등)이 분기 스냅샷에 실제로 어떻게 드러나는가.

수집이 아니라 계약 판정이다. A3b 정찰(probe-fundamentals-a3b.py)과 같은
형태를 따른다 — 이 파일이 다시 재는 것은 그 파일과 다른 엔드포인트·다른 축
(연 1회가 아니라 분기 4회)이기 때문이다.

  1. rcept_no 가 오는가 · 앞 8자리가 날짜로 읽히는가        ← availableFrom 경로
  2. istc_totqy(발행주식의 총수)가 숫자로 오는가             ← A3c 의 존재 이유
  3. 4개 reprt_code(1분기·반기·3분기·사업보고서)가 전부 응답하는가
  4. ★ 액면분할 검증 — 005930(삼성전자) 2018년 4분기를 전부 조회해
     istc_totqy가 2018-05-04 분할(공지된 사실, config/policies/price.v1.json)
     전후로 실제로 바뀌는지, 바뀐다면 어느 reprt_code부터인지 직접 관찰한다.
     이게 "기중 변경을 분기 스냅샷이 어느 시점부터 반영하는가"라는, 사용자
     GO(①안)가 감수하기로 한 정밀도 한계의 실제 크기를 재는 자리다.

금액(발행주식수 자체)은 재무 수치가 아니라 구조적 사실이라 A3/A3b 정찰과
달리 값을 그대로 남긴다 — 판정 자체가 "숫자가 언제 바뀌는가"이기 때문이다.

정찰은 어떤 결과든 exit 0으로 끝낸다. 판정은 verdict 블록에 쓴다(교훈39).

입력: DART_API_KEY (환경변수) · A1a·A1b·A3 산출물
출력: data/backfill/_probe-fundamentals-a3c.json
"""
import argparse
import glob
import gzip
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import requests

A1A = "data/backfill/universe/a1a/current.jsonl"
A1B = "data/backfill/universe/a1b/delisted.jsonl"
A3_DIR = "data/backfill/fundamentals/a3"
OUT = "data/backfill/_probe-fundamentals-a3c.json"
OUT_RETEST = "data/backfill/_probe-fundamentals-a3c-retest.json"
OUT_RAWDUMP = "data/backfill/_probe-fundamentals-a3c-rawdump.json"

# 2026-08-12 첫 정찰(32건)에서 istc_totqy를 못 읽은 4건. '보통주' 행이 없고
# '합계'만 있는 케이스였다. 행 선택을 '합계' 우선으로 고쳤는데도 재검증에서
# 여전히 null이었다 — '합계' 행 자체에 istc_totqy가 비어 있거나 다른 키에
# 들어있다는 뜻이다. 원인은 원본 응답을 봐야 안다(raw_dump).
RETEST_DEFAULT = [
    ("00101220", 2025, "11013"),
    ("00101433", 2025, "11013"),
    ("00101433", 2025, "11014"),
    ("00100717", 2016, "11013"),
]
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")
KST = timezone(timedelta(hours=9))

REPRT_CODES = [("11013", "1분기"), ("11012", "반기"), ("11014", "3분기"), ("11011", "사업보고서")]
SLEEP = 0.2

# 2026-08-12 확대 — 첫 정찰(8법인·32호출)로는 §2 규칙(PIT+우선순위+carry-forward)의
# 엣지케이스(동시접수·연속결측)가 우연히 하나씩만 걸렸다. 표본을 30~50법인으로
# 넓혀 규칙이 더 큰 표본에서도 안 깨지는지 본다. 40법인×1년×4reprt = 160호출.
SAMPLE = {
    "currentWithA3": {"corps": 30, "years": 1},
    "delistedWithA3": {"corps": 10, "years": 1},
}

# 보고서 종류 우선순위 — 동일 availableFrom(같은 날 접수)일 때 이 순서로 고른다.
# 2026-08-12 확정(사용자 GO). 값의 유무로 고르지 않는다 — 그러면 데이터 품질
# 문제가 선택 로직에 숨는다(docs/A3c-정책초안.md §2.2).
REPRT_PRIORITY = {"사업보고서": 4, "반기": 3, "3분기": 2, "1분기": 1}

# ★ 액면분할 검증 전용 표본. 무작위가 아니라 알려진 사실(50:1, 2018-05-04)로
# 고른다 — price.v1.json:13이 이미 이 분할을 정상 반영 확인한 바로 그 사례다.
SPLIT_PROBE = {"corp": "00126380", "name": "삼성전자", "year": 2018,
               "knownEvent": "2018-05-04 50:1 액면분할 (config/policies/price.v1.json 실측 확인됨)"}

DATE8 = re.compile(r"^\d{8}$")
RCEPT14 = re.compile(r"^\d{14}$")

_orig_send = requests.adapters.HTTPAdapter.send


def _send(self, request, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = (10, 60)
    return _orig_send(self, request, **kw)


requests.adapters.HTTPAdapter.send = _send


def dart_get(endpoint, params):
    """(json, dartStatus, error). 키는 로그·산출물에 절대 넣지 않는다."""
    q = {"crtfc_key": KEY, **params}
    try:
        r = requests.get(f"{BASE}/{endpoint}", params=q)
    except Exception as e:  # noqa: BLE001
        return None, "EXC", f"{type(e).__name__}: {str(e)[:150]}"
    body = r.content or b""
    if not (200 <= r.status_code < 300):
        return None, f"HTTP{r.status_code}", f"HTTP {r.status_code}"
    try:
        j = r.json()
    except Exception as e:  # noqa: BLE001
        return None, "PARSE", f"{type(e).__name__}: {str(e)[:150]}"
    st = str(j.get("status", ""))
    if st != "000":
        return None, st, str(j.get("message", ""))[:150]
    return j, "000", None


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def load_a3_index():
    idx = {}
    for p in sorted(glob.glob(f"{A3_DIR}/*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                k = (r["corp"], r["fiscalYear"])
                if k not in idx or r["availableFrom"] > idx[k]["availableFrom"]:
                    idx[k] = {"rceptNo": r.get("rceptNo"), "availableFrom": r["availableFrom"]}
    return idx


def pick_sample(a3_idx):
    cur = {r["corp"] for r in load_jsonl(A1A) if r.get("corp")}
    dele = {r["corp"] for r in load_jsonl(A1B) if r.get("corp")}
    a3_corps = {c for c, _ in a3_idx}
    years_by_corp = defaultdict(list)
    for c, y in a3_idx:
        years_by_corp[c].append(y)

    def take(pool, n_corps, n_years, group):
        out = []
        for c in sorted(pool):
            if len(out) >= n_corps:
                break
            ys = sorted(years_by_corp.get(c, []), reverse=True)[:n_years]
            if len(ys) < n_years:
                continue
            out.append({"corp": c, "years": ys, "group": group})
        return out

    picks = []
    picks += take(cur & a3_corps, SAMPLE["currentWithA3"]["corps"],
                  SAMPLE["currentWithA3"]["years"], "currentWithA3")
    picks += take(dele & a3_corps, SAMPLE["delistedWithA3"]["corps"],
                  SAMPLE["delistedWithA3"]["years"], "delistedWithA3")
    return picks


def num(x):
    """"1,234" 형태를 정수로. 숫자로 안 읽히면 None(0으로 지어내지 않는다)."""
    s = str(x or "").replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def probe_cell(corp, year, reprt_code, reprt_label):
    """한 (corp, fiscalYear, reprt_code) 조회."""
    obs = {"corp": corp, "fiscalYear": year, "reprtCode": reprt_code, "reprtLabel": reprt_label}
    j, st, err = dart_get("stockTotqySttus.json", {
        "corp_code": corp, "bsns_year": str(year), "reprt_code": reprt_code})
    obs["dartStatus"] = st
    if err:
        obs["error"] = err
    rows = (j or {}).get("list") or []
    obs["rowCount"] = len(rows)
    if not rows:
        return obs

    rcepts = {str(r.get("rcept_no") or "") for r in rows}
    obs["rceptNoValues"] = len(rcepts)
    rc = sorted(rcepts)[-1] if rcepts else ""
    obs["rceptNoPresent"] = bool(rc)
    obs["rceptNoFormatOk"] = bool(RCEPT14.match(rc))
    avail = rc[:8] if len(rc) >= 8 else ""
    obs["availableFrom"] = avail if DATE8.match(avail) else None
    obs["availableFromParsable"] = obs["availableFrom"] is not None

    obs["stlmDtPresent"] = any(r.get("stlm_dt") for r in rows)
    obs["stlmDtRaw"] = sorted({str(r.get("stlm_dt") or "") for r in rows})[:3]

    # istc_totqy — '보통주' 행을 1순위로 찾는다. 없으면 '합계' 행(2026-08-12
    # 재검증에서 추가 — 32건 중 4건이 보통주/우선주 구분 없이 합계만 낸다는 걸
    # 실측으로 확인했다). 둘 다 없으면 임의로 다른 행(rows[0] 등)에서 값을
    # 만들지 않는다 — 뭘 읽었는지 모르는 값을 istc_totqy로 자칭하는 것이
    # rows[0] 폴백의 실제 위험이었다.
    def norm(x):
        return str(x or "").replace(" ", "")
    stock_rows = [r for r in rows if "보통주" in norm(r.get("se", ""))]
    if not stock_rows:
        stock_rows = [r for r in rows if norm(r.get("se", "")) == "합계"]
    target = stock_rows[0] if stock_rows else None
    obs["seSample"] = sorted({norm(r.get("se")) for r in rows})[:6]
    obs["istcTotqySelectedFrom"] = norm(target.get("se")) if target else None
    if target is None:
        obs["istcTotqy"] = None
        obs["istcTotqyRowFound"] = False
        obs["isuStockTotqy"] = None
        obs["distbStockCo"] = None
    else:
        obs["istcTotqy"] = num(target.get("istc_totqy"))
        obs["istcTotqyRowFound"] = obs["istcTotqy"] is not None
        obs["isuStockTotqy"] = num(target.get("isu_stock_totqy"))
        obs["distbStockCo"] = num(target.get("distb_stock_co"))
    return obs


def verdict(obs_all):
    got = [o for o in obs_all if o.get("rowCount")]
    n = len(got)

    def rate(key):
        return round(sum(1 for o in got if o.get(key)) / n, 4) if n else None

    v = {
        "respondedCells": n, "totalCells": len(obs_all),
        "rceptNoPresentRate": rate("rceptNoPresent"),
        "rceptNoFormatOkRate": rate("rceptNoFormatOk"),
        "availableFromParsableRate": rate("availableFromParsable"),
        "istcTotqyRowFoundRate": rate("istcTotqyRowFound"),
        "byReprtCode": {},
    }
    for code, label in REPRT_CODES:
        grp = [o for o in obs_all if o.get("reprtCode") == code]
        v["byReprtCode"][label] = {
            "cells": len(grp),
            "responded": sum(1 for o in grp if o.get("rowCount")),
            "dartStatus": dict(Counter(o.get("dartStatus") for o in grp)),
        }

    v["canAnchorPit"] = bool(n) and v["availableFromParsableRate"] == 1.0
    v["canReadIstcTotqy"] = bool(n) and v["istcTotqyRowFoundRate"] == 1.0

    blockers = []
    if not v["canAnchorPit"]:
        blockers.append("rcept_no 로 availableFrom 을 못 만든다")
    if not v["canReadIstcTotqy"]:
        blockers.append("istc_totqy 를 숫자로 못 읽는다 — A3c 의 존재 이유가 흔들린다")
    v["blockers"] = blockers
    v["go"] = not blockers
    return v


def split_verdict(split_obs):
    """액면분할 관측 판정 — 정밀도 한계의 실제 크기."""
    got = [o for o in split_obs if o.get("istcTotqy") is not None]
    if len(got) < 2:
        return {"measured": False, "reason": "istc_totqy 관측이 2건 미만이라 변화를 못 잰다"}
    # reprt_code(11011~11014)는 발행 순서가 아니라 임의 코드라 그걸로 정렬하면
    # 안 된다(1분기 11013 < 반기 11012 < 3분기 11014 < 사업보고서 11011, 문자열
    # 순서와 실제 시간 순서가 다르다) — 실제 공시일(availableFrom)로 정렬한다.
    got.sort(key=lambda o: (o["fiscalYear"], o.get("availableFrom") or ""))
    values = [(o["reprtLabel"], o["istcTotqy"], o.get("availableFrom")) for o in got]
    ratios = []
    for i in range(1, len(values)):
        prev, cur = values[i - 1][1], values[i][1]
        if prev:
            ratios.append(round(cur / prev, 4))
    return {
        "measured": True,
        "sequence": values,
        "quarterOverQuarterRatios": ratios,
        "note": "50:1 분할이면 어느 분기 사이에 ratio≈50이 한 번 나타나야 한다. "
                "그 분기의 availableFrom이 실제 분할일(2018-05-04)보다 얼마나 "
                "늦는지가 이번 정책 결정(①안)이 감수한 정밀도 한계의 실측값이다.",
    }


def select_with_carryforward(reports, as_of):
    """확정된 A3c PIT 규칙(docs/A3c-정책초안.md §2) — 이 함수 하나가 규칙의
    단일 구현이다. reports: [{availableFrom, value(or None='-'), tag}].

      1  availableFrom <= as_of 인 후보만 본다 (PIT)
      2  그중 가장 최신 availableFrom을 고른다
      3  같은 날짜에 여럿이면 REPRT_PRIORITY로 정한다(값의 유무로 정하지 않는다)
      4  그 보고서 값이 결측이면, 같은 날짜의 다른 보고서로 옆으로 새지 않고
         그 이전(더 과거) 날짜의 가장 최근 정상값으로 carry-forward한다
      5  이전 정상값 자체가 없으면 None이다(지어내지 않는다)
    """
    eligible = [r for r in reports if r["availableFrom"] <= as_of]
    if not eligible:
        return {"value": None, "source": None}
    max_date = max(r["availableFrom"] for r in eligible)
    same_date = sorted([r for r in eligible if r["availableFrom"] == max_date],
                        key=lambda r: REPRT_PRIORITY.get(r["tag"], 0), reverse=True)
    top = same_date[0]
    if top["value"] is not None:
        return {"value": top["value"], "source": "DIRECT", "from": top["availableFrom"], "tag": top["tag"]}
    earlier = sorted([r for r in eligible if r["availableFrom"] < max_date],
                      key=lambda r: r["availableFrom"])
    for r in reversed(earlier):
        if r["value"] is not None:
            return {"value": r["value"], "source": "CARRY_FORWARD", "from": r["availableFrom"],
                    "tag": r["tag"], "selectedButMissing": top["tag"]}
    return {"value": None, "source": None}


def replay_summary(obs_all):
    """§2 규칙을 표본 전체에 재생해 지금 확정할 수 있는 지표를 낸다. 판정(go/NO-GO)은
    안 한다 — 이건 acceptance 임계를 아직 안 정한 초안 단계이고, 숫자만 사람이 본다."""
    by_corp_year = {}
    for o in obs_all:
        if o.get("dartStatus") != "000":
            continue
        by_corp_year.setdefault((o["corp"], o["fiscalYear"]), []).append(
            {"availableFrom": o.get("availableFrom") or "", "value": o.get("istcTotqy"), "tag": o["reprtLabel"]})

    directCount = carryCount = neverCount = 0
    coFilingCorps = []
    maxConsecutiveMissing = 0
    order = ["1분기", "반기", "3분기", "사업보고서"]

    for (corp, fy), reports in by_corp_year.items():
        # 동시접수 — 서로 다른 보고서 종류가 같은 availableFrom을 쓰는가
        dates = {}
        for r in reports:
            dates.setdefault(r["availableFrom"], []).append(r["tag"])
        for d, tags in dates.items():
            if len(tags) > 1:
                coFilingCorps.append({"corp": corp, "fiscalYear": fy, "availableFrom": d, "tags": tags})

        # 연속 결측 — 보고서 발행 순서(1분기→반기→3분기→사업보고서) 기준
        ordered = sorted(reports, key=lambda r: order.index(r["tag"]) if r["tag"] in order else 99)
        run = 0
        for r in ordered:
            if r["value"] is None:
                run += 1
                maxConsecutiveMissing = max(maxConsecutiveMissing, run)
            else:
                run = 0

        # 각 보고서 접수 직후 시점으로 asOf를 잡아 규칙을 재생한다
        if not any(r["value"] is not None for r in reports):
            neverCount += 1
            continue
        for r in reports:
            res = select_with_carryforward(reports, r["availableFrom"])
            if res["source"] == "DIRECT":
                directCount += 1
            elif res["source"] == "CARRY_FORWARD":
                carryCount += 1

    total = directCount + carryCount
    return {
        "corpYearsObserved": len(by_corp_year),
        "directRatio": round(directCount / total, 4) if total else None,
        "carryForwardRatio": round(carryCount / total, 4) if total else None,
        "neverValidRatio": round(neverCount / len(by_corp_year), 4) if by_corp_year else None,
        "coFilingCount": len(coFilingCorps),
        "coFilingCases": coFilingCorps,
        "maxConsecutiveMissing": maxConsecutiveMissing,
    }


def retest_only(triples) -> int:
    """실패한 셀만 다시 조회한다. 원본 정찰 산출물(OUT)은 건드리지 않는다 —
    첫 실측 증거와 재검증 증거를 같은 파일에서 덮어쓰면 무엇이 바뀌었는지
    되짚을 근거가 사라진다."""
    t0 = time.time()
    code_label = dict(REPRT_CODES)
    out = {"probe": "A3c-retest", "probedAt": datetime.now(KST).isoformat(timespec="seconds"),
           "endpoint": "stockTotqySttus.json", "retestOf": OUT, "cells": triples}

    if not KEY:
        out["aborted"] = True
        out["abortReason"] = "DART_API_KEY 없음"
        _write(out, OUT_RETEST)
        print("중단: DART_API_KEY 없음")
        return 0

    print(f"A3c 재검증 — {len(triples)}셀 (행 선택 로직 수정 후)")
    obs_all = []
    for corp, year, code in triples:
        label = code_label.get(code, code)
        o = probe_cell(corp, year, code, label)
        obs_all.append(o)
        print(f"  {corp} {year} {label:6} status={o['dartStatus']} "
              f"istc_totqy={o.get('istcTotqy')} selectedFrom={o.get('istcTotqySelectedFrom')} "
              f"seSample={o.get('seSample')}")
        time.sleep(SLEEP)

    out["observations"] = obs_all
    out["verdict"] = verdict(obs_all)
    out["calls"] = len(obs_all)
    out["elapsedSeconds"] = round(time.time() - t0, 1)
    _write(out, OUT_RETEST)

    v = out["verdict"]
    print(f"\n[재검증 판정] {'GO' if v['go'] else 'NO-GO'}")
    print(f"  istc_totqy 확보 {v['istcTotqyRowFoundRate']} (수정 전 이 4건은 0.0)")
    for b in v["blockers"]:
        print(f"  ! {b}")
    print(f"\n{OUT_RETEST} ({out['elapsedSeconds']}s)")
    return 0


def raw_dump(triples) -> int:
    """4건의 원본 응답을 가공 없이 그대로 저장한다. 파생값·판정·가설 없음 —
    istc_totqy가 실제로 어느 키에 들어오는지, 필드 구조가 보고서 종류마다
    어떻게 다른지를 눈으로 보기 위한 것뿐이다."""
    t0 = time.time()
    out = {"probe": "A3c-rawdump", "probedAt": datetime.now(KST).isoformat(timespec="seconds"),
           "endpoint": "stockTotqySttus.json", "note": "가공 없는 원본 list 응답. 판정 없음.",
           "cells": []}

    if not KEY:
        out["aborted"] = True
        out["abortReason"] = "DART_API_KEY 없음"
        _write(out, OUT_RAWDUMP)
        print("중단: DART_API_KEY 없음")
        return 0

    print(f"A3c 원본 덤프 — {len(triples)}셀 (판정 없음, 원본 행만 저장)")
    for corp, year, code in triples:
        j, st, err = dart_get("stockTotqySttus.json", {
            "corp_code": corp, "bsns_year": str(year), "reprt_code": code})
        rows = (j or {}).get("list") or []
        out["cells"].append({
            "corp": corp, "fiscalYear": year, "reprtCode": code,
            "dartStatus": st, "error": err, "rowCount": len(rows),
            "rawRows": rows,
        })
        print(f"  {corp} {year} {code}  status={st}  rows={len(rows)}  "
              f"keys={sorted(rows[0].keys()) if rows else []}")
        time.sleep(SLEEP)

    out["elapsedSeconds"] = round(time.time() - t0, 1)
    _write(out, OUT_RAWDUMP)
    print(f"\n{OUT_RAWDUMP} ({out['elapsedSeconds']}s)")
    return 0


def main() -> int:
    t0 = time.time()
    out = {"probe": "A3c", "probedAt": datetime.now(KST).isoformat(timespec="seconds"),
           "endpoint": "stockTotqySttus.json", "reprtCodes": REPRT_CODES,
           "sampleSpec": SAMPLE, "splitProbeSpec": SPLIT_PROBE}

    if not KEY:
        out["aborted"] = True
        out["abortReason"] = "DART_API_KEY 없음"
        _write(out)
        print("중단: DART_API_KEY 없음")
        return 0

    a3_idx = load_a3_index()
    picks = pick_sample(a3_idx)
    out["sample"] = picks
    planned = sum(len(p["years"]) * len(REPRT_CODES) for p in picks) + len(REPRT_CODES)
    out["plannedCalls"] = planned
    print(f"A3c 정찰 — 표본 {len(picks)}법인 · {planned}호출 (액면분할 검증 4호출 포함)")

    obs_all = []
    for p in picks:
        for y in p["years"]:
            for code, label in REPRT_CODES:
                o = probe_cell(p["corp"], y, code, label)
                o["group"] = p["group"]
                obs_all.append(o)
                print(f"  {p['group']:16} {p['corp']} {y} {label:6} "
                      f"status={o['dartStatus']} istc_totqy={o.get('istcTotqy')}")
                time.sleep(SLEEP)

    print(f"\n★ 액면분할 검증 — {SPLIT_PROBE['name']} {SPLIT_PROBE['year']} 전 분기")
    split_obs = []
    for code, label in REPRT_CODES:
        o = probe_cell(SPLIT_PROBE["corp"], SPLIT_PROBE["year"], code, label)
        split_obs.append(o)
        print(f"  {label:6} status={o['dartStatus']} istc_totqy={o.get('istcTotqy')} "
              f"availableFrom={o.get('availableFrom')}")
        time.sleep(SLEEP)

    out["observations"] = obs_all
    out["splitProbeObservations"] = split_obs
    out["verdict"] = verdict(obs_all)
    out["splitVerdict"] = split_verdict(split_obs)
    # docs/A3c-정책초안.md §2 규칙을 표본 전체에 재생한다. go/NO-GO 판정은 안
    # 한다 — acceptance 임계를 아직 안 정했다(§5, 표본 확대 후 결정).
    out["replaySummary"] = replay_summary(obs_all + split_obs)
    out["calls"] = len(obs_all) + len(split_obs)
    out["elapsedSeconds"] = round(time.time() - t0, 1)
    _write(out)

    v = out["verdict"]
    print(f"\n[판정] {'GO' if v['go'] else 'NO-GO'}")
    print(f"  응답 {v['respondedCells']}/{v['totalCells']} 셀")
    print(f"  rcept_no 존재 {v['rceptNoPresentRate']} · istc_totqy 확보 {v['istcTotqyRowFoundRate']}")
    for b in v["blockers"]:
        print(f"  ! {b}")
    print(f"  액면분할 관측: {json.dumps(out['splitVerdict'], ensure_ascii=False)}")
    print(f"\n[replay 요약] {json.dumps(out['replaySummary'], ensure_ascii=False)}")
    print(f"\n{OUT} ({out['elapsedSeconds']}s)")
    return 0


def _write(out, path=OUT):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def parse_only(s):
    """'corp:year:reprtCode,corp:year:reprtCode,...' 를 튜플 목록으로."""
    triples = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        corp, year, code = part.split(":")
        triples.append((corp, int(year), code))
    return triples


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None,
                     help="실패 셀만 재조회. 'corp:year:reprtCode,...' 또는 생략 시 기본 4건")
    ap.add_argument("--only-default", action="store_true",
                     help="RETEST_DEFAULT(첫 정찰에서 실패한 4건)을 재조회한다")
    ap.add_argument("--raw-dump", action="store_true",
                     help="RETEST_DEFAULT 4건의 원본 응답을 가공 없이 저장한다(판정 없음)")
    args = ap.parse_args()

    if args.raw_dump:
        raise SystemExit(raw_dump(RETEST_DEFAULT))
    elif args.only:
        raise SystemExit(retest_only(parse_only(args.only)))
    elif args.only_default:
        raise SystemExit(retest_only(RETEST_DEFAULT))
    else:
        raise SystemExit(main())
