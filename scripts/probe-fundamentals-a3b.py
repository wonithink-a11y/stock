#!/usr/bin/env python3
"""A3b 정찰 — alotMatter가 PIT 앵커를 주는가. 수집이 아니라 계약 판정이다.

A3가 밟은 지뢰를 다시 밟지 않으려는 정찰이다. FN-1.0은 `fnlttSinglAcntAll`을 골랐다가
정찰에서 `thstrm_dt`가 240건 전건 없음을 보고 뒤집었다 — 회계기간말을 못 읽으면
계약 1(availableFrom > periodEnd)을 **잴 수단이 없고, 잴 수 없는 계약은 계약이 아니다**
(교훈50). `alotMatter`는 A3와 다른 엔드포인트라 필드 이름이 다르므로, A3에서 참인 것을
옮겨 쓰지 않고 여기서 다시 잰다.

  1. rcept_no 가 오는가 · 앞 8자리가 날짜로 읽히는가     ← availableFrom 의 유일한 경로
  2. stlm_dt(결산기준일)가 오는가 · 어떤 형태인가         ← periodEnd 의 경로
  3. availableFrom 과 periodEnd 의 **방향**               ← A3 계약은 > 다. 실측으로 판정한다
  4. 한 (corp, fiscalYear) 응답 안에서 rcept_no 가 일관된가
  5. A3 산출물의 rceptNo 와 같은가 — 다르면 두 실행 사이의 정정공시다
  6. 주당순이익·주당현금배당금 행을 실제로 찾는가          ← A3b 의 존재 이유

**금액을 남기지 않는다.** EPS·배당금은 재무 수치이므로 값이 아니라 '찾았는가·숫자로
읽히는가'만 남긴다(A3 정찰과 같은 원칙).

표본은 결정적으로 고른다 — corp 오름차순이라 다시 돌려도 같은 표본이고, 산출물에
그대로 적어 나중에 되짚을 수 있다.

정찰은 어떤 결과든 exit 0으로 끝낸다. 판정은 verdict 블록에 쓴다(교훈39).

입력: DART_API_KEY (환경변수) · A1a·A1b·A3 산출물
출력: data/backfill/_probe-fundamentals-a3b.json
"""
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
A3_DIAG = f"{A3_DIR}/_diagnostics.json"
OUT = "data/backfill/_probe-fundamentals-a3b.json"
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")
KST = timezone(timedelta(hours=9))

REPRT_ANNUAL = "11011"
SLEEP = 0.2

# 표본 구성. 32호출 예산을 축에 배분한다 — 무작위 32건은 갈리는 축을 못 밟는다.
SAMPLE = {
    "currentWithA3": {"corps": 10, "years": 2},   # 20 — A3b 의 실제 목표 집단
    "delistedWithA3": {"corps": 4, "years": 2},   #  8 — 격자에 포함하기로 한 440 그룹
    "noA3": {"corps": 4, "years": 1},             #  4 — 599 그룹. 응답이 오는지 본다
}

DATE8 = re.compile(r"^\d{8}$")
RCEPT14 = re.compile(r"^\d{14}$")
# stlm_dt 의 형태를 모른다. A3 의 thstrm_dt 는 "2023.12.31 현재" 같은 문장형이었다.
# 그래서 정규식으로 날짜를 캐내되 **원문도 함께 남긴다** — 형태 자체가 이 정찰의 산출이다.
DT_IN_TEXT = re.compile(r"(\d{4})[.\-/]?(\d{2})[.\-/]?(\d{2})")

LAST_HTTP = {"endpoint": None, "status": None, "dartStatus": None, "bytes": None}

_orig_send = requests.adapters.HTTPAdapter.send


def _send(self, request, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = (10, 60)
    return _orig_send(self, request, **kw)


requests.adapters.HTTPAdapter.send = _send


def dart_get(endpoint, params):
    """(json, dartStatus, error). 키는 로그·산출물에 절대 넣지 않는다.

    DART는 조회 실패도 HTTP 200 + status 필드로 돌려준다. HTTP만 보면 '데이터 없음'과
    '정상'이 구분되지 않으므로 두 축을 다 남긴다(A3 정찰과 같은 처리).
    """
    q = {"crtfc_key": KEY, **params}
    try:
        r = requests.get(f"{BASE}/{endpoint}", params=q)
    except Exception as e:  # noqa: BLE001
        LAST_HTTP.update(endpoint=endpoint, status=None, dartStatus=None, bytes=None)
        return None, "EXC", f"{type(e).__name__}: {str(e)[:150]}"
    body = r.content or b""
    LAST_HTTP.update(endpoint=endpoint, status=r.status_code, bytes=len(body))
    if not (200 <= r.status_code < 300):
        return None, f"HTTP{r.status_code}", f"HTTP {r.status_code}"
    try:
        j = r.json()
    except Exception as e:  # noqa: BLE001
        return None, "PARSE", f"{type(e).__name__}: {str(e)[:150]}"
    st = str(j.get("status", ""))
    LAST_HTTP["dartStatus"] = st
    if st != "000":
        return None, st, str(j.get("message", ""))[:150]
    return j, "000", None


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def load_a3_index():
    """(corp, fiscalYear) → {rceptNo, availableFrom}. A3 산출물이 단일 출처다.

    #5(정정공시 대조)의 기준선이고 표본 선정의 입력이기도 하다.
    """
    idx = {}
    for p in sorted(glob.glob(f"{A3_DIR}/*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                k = (r["corp"], r["fiscalYear"])
                # 정정공시로 같은 키가 여럿이면 availableFrom 이 가장 큰 것 = 최신 보고서.
                # alotMatter 도 최신을 줄 것이므로 대조 상대를 맞춘다.
                if k not in idx or r["availableFrom"] > idx[k]["availableFrom"]:
                    idx[k] = {"rceptNo": r.get("rceptNo"),
                              "availableFrom": r["availableFrom"]}
    return idx


def pick_sample(a3_idx):
    """결정적 표본. corp 오름차순이라 재실행해도 같다."""
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

    # 599 그룹 — A3 데이터가 없고 recordGaps 항목도 없는 법인.
    # 그 둘의 차이가 '조회 안 함'과 '조회했더니 없음'이며, 지금 구분이 안 된다(교훈75).
    gaps = {}
    if os.path.exists(A3_DIAG):
        gaps = json.load(open(A3_DIAG, encoding="utf-8")).get("recordGaps") or {}
    no_a3 = sorted((cur | dele) - a3_corps - set(gaps))
    for c in no_a3[:SAMPLE["noA3"]["corps"]]:
        picks.append({"corp": c, "years": [2024], "group": "noA3"})
    return picks


def probe_one(corp, year, a3_idx):
    """한 (corp, fiscalYear)를 조회하고 사실만 기록한다. 금액은 남기지 않는다."""
    obs = {"corp": corp, "fiscalYear": year}
    j, st, err = dart_get("alotMatter.json", {
        "corp_code": corp, "bsns_year": str(year), "reprt_code": REPRT_ANNUAL})
    obs["dartStatus"] = st
    if err:
        obs["error"] = err
    rows = (j or {}).get("list") or []
    obs["rowCount"] = len(rows)
    if not rows:
        return obs

    # 1·4 — rcept_no 존재와 응답 내 일관성
    rcepts = {str(r.get("rcept_no") or "") for r in rows}
    obs["rceptNoValues"] = len(rcepts)
    rc = sorted(rcepts)[-1] if rcepts else ""
    obs["rceptNoPresent"] = bool(rc)
    obs["rceptNoFormatOk"] = bool(RCEPT14.match(rc))
    obs["rceptNoConsistent"] = len(rcepts) == 1
    avail = rc[:8] if len(rc) >= 8 else ""
    obs["availableFrom"] = avail if DATE8.match(avail) else None
    obs["availableFromParsable"] = obs["availableFrom"] is not None

    # 2 — stlm_dt. 형태를 모르므로 원문을 그대로 남긴다. 그것이 이 정찰의 산출이다.
    stlm = {str(r.get("stlm_dt") or "") for r in rows if r.get("stlm_dt") is not None}
    obs["stlmDtPresent"] = any(bool(s) for s in stlm)
    obs["stlmDtRaw"] = sorted(stlm)[:3]
    obs["stlmDtValues"] = len(stlm)
    pe = None
    for s in sorted(stlm, reverse=True):
        found = DT_IN_TEXT.findall(s)
        if found:
            pe = "".join(found[-1])
            break
    obs["periodEnd"] = pe
    obs["periodEndParsable"] = pe is not None

    # 3 — 방향. A3 계약은 availableFrom > periodEnd 다. 판정은 실측이 한다.
    if obs["availableFrom"] and pe:
        obs["pitDirection"] = ("after" if obs["availableFrom"] > pe
                               else "same" if obs["availableFrom"] == pe else "before")
        obs["disclosureLagDays"] = (
            datetime.strptime(obs["availableFrom"], "%Y%m%d")
            - datetime.strptime(pe, "%Y%m%d")).days

    # 5 — A3 의 rceptNo 와 대조. 다르면 두 실행 사이의 정정공시이고 결함이 아니다.
    a3 = a3_idx.get((corp, year))
    if a3 and a3.get("rceptNo"):
        obs["a3RceptNo"] = a3["rceptNo"]
        obs["rceptNoMatchesA3"] = (rc == str(a3["rceptNo"]))

    # 6 — EPS·배당 행. 금액은 남기지 않고 '찾았는가·숫자로 읽히는가'만 남긴다.
    def norm(x):
        return str(x or "").replace(" ", "")

    def numeric(x):
        s = str(x or "").replace(",", "").replace("-", "").strip()
        return s.isdigit() and s != ""

    eps_row = next((r for r in rows if "주당순이익" in norm(r.get("se"))), None)
    div_row = next((r for r in rows
                    if "주당현금배당금" in norm(r.get("se"))
                    and "보통주" in norm(r.get("stock_knd"))), None) \
        or next((r for r in rows if "주당현금배당금" in norm(r.get("se"))), None)
    obs["epsRowFound"] = eps_row is not None
    obs["epsThstrmNumeric"] = numeric(eps_row.get("thstrm")) if eps_row else False
    obs["dividendRowFound"] = div_row is not None
    obs["dividendThstrmNumeric"] = numeric(div_row.get("thstrm")) if div_row else False
    obs["seSample"] = sorted({norm(r.get("se")) for r in rows})[:12]
    return obs


def verdict(obs_all):
    """판정. 게이트가 아니라 계약을 확정할 수 있는지에 대한 답이다."""
    got = [o for o in obs_all if o.get("rowCount")]
    n = len(got)

    def rate(key):
        return round(sum(1 for o in got if o.get(key)) / n, 4) if n else None

    v = {
        "respondedCells": n,
        "totalCells": len(obs_all),
        "rceptNoPresentRate": rate("rceptNoPresent"),
        "rceptNoFormatOkRate": rate("rceptNoFormatOk"),
        "rceptNoConsistentRate": rate("rceptNoConsistent"),
        "availableFromParsableRate": rate("availableFromParsable"),
        "stlmDtPresentRate": rate("stlmDtPresent"),
        "periodEndParsableRate": rate("periodEndParsable"),
        "epsRowFoundRate": rate("epsRowFound"),
        "dividendRowFoundRate": rate("dividendRowFound"),
        "pitDirection": dict(Counter(o.get("pitDirection") for o in got
                                     if o.get("pitDirection"))),
        "rceptNoVsA3": dict(Counter(o.get("rceptNoMatchesA3") for o in got
                                    if "rceptNoMatchesA3" in o)),
        "byGroup": {},
    }
    for g in ("currentWithA3", "delistedWithA3", "noA3"):
        grp = [o for o in obs_all if o.get("group") == g]
        v["byGroup"][g] = {
            "cells": len(grp),
            "responded": sum(1 for o in grp if o.get("rowCount")),
            "dartStatus": dict(Counter(o.get("dartStatus") for o in grp)),
        }

    # 계약을 확정할 수 있는가. 못 재는 것을 통과로 적지 않는다(교훈50·57).
    v["canAnchorPit"] = bool(n) and v["availableFromParsableRate"] == 1.0
    v["canMeasurePeriodEnd"] = bool(n) and v["periodEndParsableRate"] == 1.0
    v["pitContractDirection"] = (
        "availableFrom > periodEnd" if v["pitDirection"].get("after") == n
        else "MIXED_OR_UNEXPECTED" if v["pitDirection"] else "UNMEASURED")
    v["opensValuation"] = bool(n) and v["epsRowFoundRate"] == 1.0

    blockers = []
    if not v["canAnchorPit"]:
        blockers.append("rcept_no 로 availableFrom 을 못 만든다 — PIT 앵커가 없으면 "
                        "A3b 는 A3 가 fnlttSinglAcntAll 에서 겪은 것과 같은 상태다")
    if not v["canMeasurePeriodEnd"]:
        blockers.append("stlm_dt 로 periodEnd 를 못 읽는다 — 계약 1을 잴 수단이 없다. "
                        "A3 의 periodEnd 를 빌려 쓰면 A3 데이터로 A3b 를 재는 것이 되어 "
                        "A3b 자신의 파싱 오류를 못 잡는다")
    if v["pitContractDirection"] == "MIXED_OR_UNEXPECTED":
        blockers.append(f"availableFrom 과 periodEnd 의 방향이 A3 계약(>)과 다르다: "
                        f"{v['pitDirection']}")
    if not v["opensValuation"]:
        blockers.append("주당순이익 행을 전건에서 찾지 못했다 — A3b 의 존재 이유가 흔들린다")
    v["blockers"] = blockers
    v["go"] = not blockers
    return v


def main() -> int:
    t0 = time.time()
    out = {"probe": "A3b", "probedAt": datetime.now(KST).isoformat(timespec="seconds"),
           "endpoint": "alotMatter.json", "reprtCode": REPRT_ANNUAL,
           "sampleSpec": SAMPLE}

    if not KEY:
        out["aborted"] = True
        out["abortReason"] = "DART_API_KEY 없음"
        _write(out)
        print("중단: DART_API_KEY 없음")
        return 0            # 정찰은 exit 0. 산출물이 사유를 말한다

    a3_idx = load_a3_index()
    out["a3IndexSize"] = len(a3_idx)
    picks = pick_sample(a3_idx)
    out["sample"] = picks
    planned = sum(len(p["years"]) for p in picks)
    out["plannedCalls"] = planned
    print(f"A3b 정찰 — 표본 {len(picks)}법인 · {planned}호출 "
          f"(A3 인덱스 {len(a3_idx)}셀)")

    obs_all, calls = [], 0
    for p in picks:
        for y in p["years"]:
            o = probe_one(p["corp"], y, a3_idx)
            o["group"] = p["group"]
            obs_all.append(o)
            calls += 1
            print(f"  {p['group']:16} {p['corp']} {y}  "
                  f"status={o['dartStatus']} rows={o.get('rowCount', 0)} "
                  f"rcept={o.get('rceptNoPresent')} stlm={o.get('stlmDtPresent')} "
                  f"eps={o.get('epsRowFound')}")
            time.sleep(SLEEP)

    out["calls"] = calls
    out["observations"] = obs_all
    out["verdict"] = verdict(obs_all)
    out["elapsedSeconds"] = round(time.time() - t0, 1)
    _write(out)

    v = out["verdict"]
    print(f"\n[판정] {'GO' if v['go'] else 'NO-GO'}")
    print(f"  응답 {v['respondedCells']}/{v['totalCells']} 셀")
    print(f"  rcept_no 존재 {v['rceptNoPresentRate']} · 형식 {v['rceptNoFormatOkRate']} "
          f"· 응답 내 일관 {v['rceptNoConsistentRate']}")
    print(f"  stlm_dt 존재 {v['stlmDtPresentRate']} · periodEnd 파싱 {v['periodEndParsableRate']}")
    print(f"  PIT 방향 {v['pitDirection']} → {v['pitContractDirection']}")
    print(f"  A3 rceptNo 대조 {v['rceptNoVsA3']}")
    print(f"  EPS 행 {v['epsRowFoundRate']} · 배당 행 {v['dividendRowFoundRate']}")
    print(f"  그룹별 {json.dumps(v['byGroup'], ensure_ascii=False)}")
    for b in v["blockers"]:
        print(f"  ! {b}")
    print(f"\n{OUT} ({out['elapsedSeconds']}s)")
    return 0


def _write(out):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    raise SystemExit(main())
