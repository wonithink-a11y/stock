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

# 일반 표본. 32호출 예산(6법인×1년×4reprt) — A3b와 같은 규모.
SAMPLE = {
    "currentWithA3": {"corps": 6, "years": 1},
    "delistedWithA3": {"corps": 2, "years": 1},
}

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
