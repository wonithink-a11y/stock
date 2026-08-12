#!/usr/bin/env python3
"""A3c — 발행주식총수 (FN-1.6)

계약은 `docs/A3c-정책초안.md`, 정의는 `config/policies/fundamentals.v1.json`의
`a3c` 블록이 단일 산출점이다. 이 스크립트에 소스·격자·임계를 하드코딩하지 않는다 —
회귀(`test-fundamentals-a3c.py`)가 그것을 강제한다.

A3b의 복사에 가깝다. **A3b와 다른 곳은 넷**이고, 다른 코드는 전부 그 넷 중 하나다.

  1. 격자 단위가 (corp, fiscalYear, reprtCode)다
     A3b는 사업보고서 1회지만 A3c는 reprtCode 4종(1분기·반기·3분기·사업보고서)을
     전부 조회한다. (corp, fiscalYear) 하나가 최대 4개 레코드를 낳는다.
  2. 조기 종료는 '그 해 4개 reprtCode가 전부 013'일 때만 건다
     하나라도 데이터가 있으면 그 해는 빈 해가 아니다 — 분기보고서 의무가 없는
     회사도 사업보고서는 낼 수 있다(실측: 40법인 정찰에서 반기·사업보고서는
     100% 확보).
  3. istc_totqy 행 선택은 '보통주' → '합계' 순이고, 임의 폴백이 없다
     응답에 '-'(문자열)로 오는 결측이 실측으로 확인됐다(rawdump). rows[0] 같은
     폴백은 금지 — 어떤 행을 읽었는지 모르는 값을 istc_totqy로 자칭하지 않는다.
  4. PIT tie-break·carry-forward를 인수 조건(replay 지표)으로 확인한다
     저장은 원시 사실만 한다 — DIRECT/CARRY_FORWARD 선택 자체는 여기서 하지
     않는다(그건 조회 시점의 리졸버 몫, 이 스크립트는 안 건드린다). 다만 그
     규칙을 전체 수집분에 재생했을 때 직전 정찰(40법인)과 크게 어긋나지
     않는지는 acceptance에서 확인한다 — select_with_carryforward()는
     probe-fundamentals-a3c.py에서 그대로 가져온다(정책은 하나, 구현은 하나).

일 예산·샤드 배분은 A3의 `shard_budget()`을 가져다 쓴다(A3b와 동일).

  --shard N --shards M   담당 법인 수집 → _shards_a3c/shard-N.jsonl (Actions가 커밋)
  --finalize             병합 → 인수 조건 → 연도 분할 → gzip
  --revalidate           커밋된 산출물만으로 인수 조건 재판정 (계약 §9와 동일)
  --plan                 네트워크 없이 격자만 계산해 출력한다

입력:
  config/policies/fundamentals.v1.json      a3c 블록
  data/backfill/universe/a1a/current.jsonl  · a1b/delisted.jsonl
  data/backfill/fundamentals/a3/*.jsonl.gz  격자의 출처
출력:
  data/backfill/fundamentals/a3c/{YYYY}.jsonl.gz
  data/backfill/fundamentals/a3c/_diagnostics.json
"""
import argparse
import glob
import gzip
import importlib.util
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = "config/policies/fundamentals.v1.json"
A1A = "data/backfill/universe/a1a/current.jsonl"
A1B = "data/backfill/universe/a1b/delisted.jsonl"
A3_DIR = "data/backfill/fundamentals/a3"
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")

STAGE_VERSION = "A3c.0"
TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
CORP_RE = re.compile(r"^[0-9]{8}$")
DATE8 = re.compile(r"^\d{8}$")
RCEPT14 = re.compile(r"^\d{14}$")
DT_IN_TEXT = re.compile(r"(\d{4})[.\-/]?(\d{2})[.\-/]?(\d{2})")

fails, warns = [], []


def _load_module(name, filename):
    """하이픈 파일명은 import 문으로 못 읽는다. 모듈 최상위는 상수·함수
    정의뿐이라 부작용이 없다(A3b의 _load_a3()와 같은 이유)."""
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(ROOT, "scripts", filename))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A3 = _load_module("a3", "build-fundamentals-a3.py")
PROBE = _load_module("a3c_probe", "probe-fundamentals-a3c.py")
REPRT_CODES = PROBE.REPRT_CODES           # [(code, label), ...] — 단일 출처
REPRT_PRIORITY = PROBE.REPRT_PRIORITY     # tie-break 우선순위 — 단일 출처
select_with_carryforward = PROBE.select_with_carryforward

import requests  # noqa: E402  (A3 모듈이 requests 어댑터 가드를 먼저 걸게 둔다)


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _abort(reason, diag, path, extra=None):
    diag.update({"aborted": True, "abortReason": reason, **(extra or {})})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    sys.exit(2)


# ── DART ───────────────────────────────────────────────────────
DART_NO_DATA = "013"


def dart_get(endpoint, params, pol=None):
    """A3b와 동일한 재시도 규약. (json, dartStatus, error)."""
    attempts = (pol or {}).get("retryAttempts", 1)
    base = (pol or {}).get("retryBackoffBase", 2)
    quota_status = ((pol or {}).get("quota") or {}).get("quotaExceededStatus", "020")
    last = (None, "unknown", "unknown")
    for i in range(attempts):
        try:
            r = requests.get(f"{BASE}/{endpoint}", params={"crtfc_key": KEY, **params}, timeout=30)
        except Exception as e:  # noqa: BLE001
            last = (None, "EXC", f"{type(e).__name__}: {str(e)[:150]}")
        else:
            if not (200 <= r.status_code < 300):
                last = (None, f"HTTP{r.status_code}", f"HTTP {r.status_code}")
            else:
                try:
                    j = r.json()
                except Exception as e:  # noqa: BLE001
                    last = (None, "PARSE", f"{type(e).__name__}: {str(e)[:150]}")
                else:
                    st = str(j.get("status", ""))
                    if st == "000":
                        return j, "000", None
                    if st in (DART_NO_DATA, quota_status):
                        return None, st, str(j.get("message", ""))[:150]
                    last = (None, st, str(j.get("message", ""))[:150])
        if i < attempts - 1:
            time.sleep(base ** i)
    return last


# ── 파싱 (순수 함수 — 회귀가 여기를 밟는다) ────────────────────────
def _norm(x):
    return str(x or "").replace(" ", "")


def num(raw):
    """"1,234"|"-"|None → int|None. '-'·빈 문자열·비숫자는 전부 None이다
    (0으로 지어내지 않는다). probe-fundamentals-a3c.py의 num()과 같은 규칙."""
    s = str(raw if raw is not None else "").replace(",", "").strip()
    if not s or s == "-":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def parse_period_end(rows, field):
    """A3b의 parse_period_end와 동일 — 형태를 가정하지 않고 마지막 날짜를 캔다."""
    for raw in sorted({str(r.get(field) or "") for r in rows}, reverse=True):
        found = DT_IN_TEXT.findall(raw)
        if found:
            return "".join(found[-1])
    return None


def select_istc_row(rows):
    """'보통주' 우선, 없으면 '합계'. 둘 다 없으면 None — rows[0] 같은 임의
    폴백을 하지 않는다(2026-08-12 실측으로 확정, docs/A3c-정책초안.md §source)."""
    common = [r for r in rows if "보통주" in _norm(r.get("se"))]
    if common:
        return common[0], "보통주"
    total = [r for r in rows if _norm(r.get("se")) == "합계"]
    if total:
        return total[0], "합계"
    return None, None


def build_record(corp, ticker, year, reprt_code, reprt_label, rows):
    """응답 → 레코드 또는 (None, 사유)."""
    rcepts = sorted({str(r.get("rcept_no") or "") for r in rows if r.get("rcept_no")})
    if not rcepts:
        return None, "RCEPT_NO_MISSING"
    rc = rcepts[-1]
    if not RCEPT14.match(rc):
        return None, "RCEPT_NO_MALFORMED"
    available_from = rc[:8]
    if not DATE8.match(available_from):
        return None, "AVAILABLE_FROM_UNPARSED"

    period_end = parse_period_end(rows, "stlm_dt")
    if not period_end:
        return None, "PERIOD_END_UNPARSED"

    target, selected_from = select_istc_row(rows)
    istc_totqy = num(target.get("istc_totqy")) if target else None
    isu_stock_totqy = num(target.get("isu_stock_totqy")) if target else None
    distb_stock_co = num(target.get("distb_stock_co")) if target else None

    return {
        "corp": corp,
        "ticker": ticker,
        "fiscalYear": year,
        "reprtCode": reprt_code,
        "availableFrom": available_from,
        "rceptNo": rc,
        "periodEnd": period_end,
        "istcTotqy": istc_totqy,
        "isuStockTotqy": isu_stock_totqy,
        "distbStockCo": distb_stock_co,
        "scanStatus": "OK" if istc_totqy is not None else "EMPTY",
        "istcTotqySelectedFrom": selected_from,
    }, None


# ── 격자 (네트워크 없음 — --plan으로 따로 볼 수 있다) ─────────────
def a3_grid():
    """A3 산출물의 (corp, fiscalYear) 집합 — A3b와 같은 재사용 소스."""
    out = set()
    for p in sorted(glob.glob(f"{A3_DIR}/*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                out.add((r["corp"], r["fiscalYear"]))
    return out


def target_corps():
    out = {}
    for r in load_jsonl(A1B):
        if r.get("corp"):
            out[r["corp"]] = {"ticker": r.get("ticker"), "group": "delisted"}
    for r in load_jsonl(A1A):
        if r.get("corp"):
            out[r["corp"]] = {"ticker": r.get("ticker"), "group": "current"}
    return out


def build_grid(pol):
    """(corp → [연도...], meta). A3b build_grid와 동일한 (corp, fiscalYear) 격자다
    — reprtCode 4종은 scan_corp() 안에서 연도마다 전개된다(격자 자체는 A3b와 같다)."""
    a3c = pol["a3c"]
    mode = a3c["grid"]["mode"]
    if mode != "a3ReuseAndScanMissing":
        raise ValueError(f"a3c.grid.mode '{mode}' — 허용값은 a3ReuseAndScanMissing 뿐이다")

    corps = target_corps()
    grid_src = a3_grid()
    years_all = list(range(pol["fiscalYearFrom"], pol["fiscalYearTo"] + 1))

    reuse = defaultdict(list)
    for (c, y) in grid_src:
        if c in corps:
            reuse[c].append(y)
    for c in reuse:
        reuse[c].sort()

    missing = sorted(set(corps) - set(reuse))
    grid = {c: list(ys) for c, ys in reuse.items()}
    if a3c["grid"].get("scanMissingCorps", True):
        for c in missing:
            grid[c] = list(years_all)

    meta = {
        "gridMode": mode,
        "reuseCorps": len(reuse),
        "reuseCells": sum(len(v) for v in reuse.values()),
        "missingCorps": len(missing),
        "missingCorpsByGroup": dict(Counter(corps[c]["group"] for c in missing)),
        "targetCorps": len(corps),
        "cellMultiplier": len(REPRT_CODES),
    }
    return grid, corps, meta


# ── 수집 ───────────────────────────────────────────────────────
def scan_corp(corp, ticker, years, pol, state, counters):
    """(records, scanned, quota_hit). scanned[str(year)] = {reprtCode: status}.

    조기 종료는 '그 해 4개 reprtCode가 전부 013'일 때만 건다 — 분기보고서
    의무가 없는 회사도 사업보고서는 낼 수 있어, A3b처럼 단일 호출 결과만으로
    그 해를 판정하면 안 된다(§ 모듈 docstring 2번).
    """
    stop_after = pol["stopAfterConsecutiveEmptyYears"]
    quota_status = pol["quota"]["quotaExceededStatus"]
    recs, scanned = [], {}
    consec_empty = 0

    for y in years:
        if consec_empty >= stop_after:
            break
        year_scanned = {}
        year_had_report = False
        for code, label in REPRT_CODES:
            j, st, err = dart_get("stockTotqySttus.json", {
                "corp_code": corp, "bsns_year": str(y), "reprt_code": code}, pol)
            counters["calls"] += 1
            state["callsUsedToday"] += 1
            if st == quota_status:
                counters["quotaHits"] += 1
                return [], {}, True
            rows = (j or {}).get("list") or []
            if st != "000" or not rows:
                year_scanned[code] = st if st != "000" else "EMPTY_RESPONSE"
                counters["emptyCells"] += 1
                continue
            year_had_report = True
            rec, why = build_record(corp, ticker, y, code, label, rows)
            if rec is None:
                year_scanned[code] = f"REJECTED:{why}"
                counters["rejected"][why] += 1
                continue
            year_scanned[code] = rec["scanStatus"]  # OK | EMPTY (값 자체가 '-')
            recs.append(rec)
            time.sleep(pol["requestSleepSeconds"])
        scanned[str(y)] = year_scanned
        consec_empty = 0 if year_had_report else consec_empty + 1

    if consec_empty >= stop_after:
        remaining = [y for y in years if str(y) not in scanned]
        for y in remaining:
            scanned[str(y)] = {code: "EARLY_STOP" for code, _ in REPRT_CODES}
    return recs, scanned, False


def rec_key(r):
    return (r["corp"], r["fiscalYear"], r["availableFrom"], r["reprtCode"])


def run_shard(shard, shards, pol, limit):
    a3c = pol["a3c"]
    out = a3c["output"]
    sdir = out["stateDir"]
    os.makedirs(sdir, exist_ok=True)
    spath = f"{sdir}/_state-{shard}.json"
    dpath = f"{sdir}/_diagnostics-shard-{shard}.json"
    today = A3.today_kst()

    diag = {"stage": "A3c", "mode": "shard", "shard": shard, "shards": shards,
            "stageVersion": STAGE_VERSION, "fundamentalsPolicy": pol["version"],
            "runDate": today}

    if not KEY:
        _abort("DART_API_KEY 없음", diag, dpath)

    grid, corps, gmeta = build_grid(pol)
    diag.update(gmeta)
    mine = sorted(grid)[shard::shards]
    if limit:
        mine = mine[:limit]
        diag["smokeTest"] = True

    state = load_json(spath) if os.path.exists(spath) else {
        "shard": shard, "corpsDone": [], "scanned": {},
        "callsUsedToday": 0, "lastRunDate": None, "corpsAssigned": 0}
    if state.get("lastRunDate") != today:
        state["callsUsedToday"] = 0
        state["lastRunDate"] = today
    state["corpsAssigned"] = len(mine)

    budget, bdetail = A3.shard_budget(pol, shards, shard, state["callsUsedToday"],
                                      today, state_dir=sdir)
    diag["shardBudget"] = bdetail

    done = set(state["corpsDone"])
    todo = [c for c in mine if c not in done]
    print(f"A3c 샤드 {shard}/{shards} — 담당 {len(mine)}법인 · 완료 {len(mine)-len(todo)} "
          f"· 남음 {len(todo)}")
    print(f"  격자 {gmeta['reuseCells']}셀×4reprt 재사용 + 미확보 {gmeta['missingCorps']}법인 "
          f"· 오늘 예산 {budget - state['callsUsedToday']}/{budget}")

    records = {}
    rpath = f"{sdir}/shard-{shard}.jsonl"
    if os.path.exists(rpath):
        for r in load_jsonl(rpath):
            if r["corp"] in done:
                records[rec_key(r)] = r

    counters = {"calls": 0, "emptyCells": 0, "quotaHits": 0, "rejected": Counter()}
    budget_hit = quota_hit = False
    t0 = time.time()
    for i, corp in enumerate(todo, 1):
        if state["callsUsedToday"] >= budget:
            budget_hit = True
            break
        recs, scanned, hit_quota = scan_corp(corp, corps[corp]["ticker"], grid[corp],
                                             pol, state, counters)
        if hit_quota:
            quota_hit = True
            break
        for r in recs:
            records[rec_key(r)] = r
        state["scanned"][corp] = scanned
        done.add(corp)
        if i % 200 == 0:
            print(f"  {i}/{len(todo)} · {len(records)}행 · 호출 {state['callsUsedToday']} "
                  f"· {time.time()-t0:.0f}s")

    state["corpsDone"] = sorted(done)
    diag.update(corpsAssigned=len(mine), corpsDone=len(done),
                corpsRemaining=len(mine) - len(done),
                calls=state["callsUsedToday"], budget=budget,
                budgetExhausted=budget_hit, quotaExceeded=quota_hit,
                quotaHits=counters["quotaHits"], rowCount=len(records),
                emptyCells=counters["emptyCells"],
                rejected=dict(counters["rejected"]),
                scannedCells=sum(len(v) for v in state["scanned"].values()),
                elapsedSeconds=round(time.time() - t0, 1))

    with open(rpath, "w", encoding="utf-8", newline="\n") as f:
        for k in sorted(records):
            f.write(json.dumps(records[k], ensure_ascii=False) + "\n")
    with open(spath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    with open(dpath, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{rpath} — {len(records)}행 · 스캔 {diag['scannedCells']}셀 · "
          f"호출 {state['callsUsedToday']} · "
          f"""{'DART 일 한도 (다음 실행이 이어받는다)' if quota_hit
              else '예산 소진 (다음 실행이 이어받는다)' if budget_hit
              else '담당분 완료'}""")
    return 0


# ── replay 지표 (acceptance가 쓴다 — probe와 같은 함수) ────────────
def replay_metrics(rows):
    """select_with_carryforward()를 전체 수집분에 재생한다. probe의
    replay_summary()와 같은 계산이지만 입력이 실제 저장 레코드 형태다."""
    by_corp_year = defaultdict(list)
    for r in rows:
        by_corp_year[(r["corp"], r["fiscalYear"])].append(
            {"availableFrom": r["availableFrom"], "value": r["istcTotqy"],
             "tag": PROBE.REPRT_CODES and dict(REPRT_CODES).get(r["reprtCode"], r["reprtCode"])})

    order = ["1분기", "반기", "3분기", "사업보고서"]
    directCount = carryCount = neverCount = 0
    coFilingCases, maxRun = [], 0

    for (corp, fy), reports in by_corp_year.items():
        dates = defaultdict(list)
        for r in reports:
            dates[r["availableFrom"]].append(r["tag"])
        for d, tags in dates.items():
            if len(tags) > 1:
                coFilingCases.append({"corp": corp, "fiscalYear": fy, "availableFrom": d, "tags": tags})

        ordered = sorted(reports, key=lambda r: order.index(r["tag"]) if r["tag"] in order else 99)
        run = 0
        for r in ordered:
            if r["value"] is None:
                run += 1
                maxRun = max(maxRun, run)
            else:
                run = 0

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
    corp_years = len(by_corp_year)
    return {
        "corpYearsObserved": corp_years,
        "directRatio": round(directCount / total, 4) if total else None,
        "carryForwardRatio": round(carryCount / total, 4) if total else None,
        "neverValidRatio": round(neverCount / corp_years, 4) if corp_years else None,
        "coFilingCount": len(coFilingCases),
        "coFilingCases": coFilingCases[:20],
        "maxConsecutiveMissing": maxRun,
    }


# ── 인수 조건 ──────────────────────────────────────────────────
def validate(rows, pol, diag, from_output_only=False):
    a = pol["a3c"]["acceptance"]
    print("\n[인수 조건]")

    inject = os.environ.get("A3C_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    bad_date = [r for r in rows if not DATE8.match(r.get("availableFrom") or "")
                or not DATE8.match(r.get("periodEnd") or "")]
    chk(len(bad_date) == a["dateContractViolations"], f"날짜 계약 YYYYMMDD (위반 {len(bad_date)}건)")

    miss_pe = [r for r in rows if not r.get("periodEnd")]
    chk(len(miss_pe) == a["periodEndMissing"], f"periodEnd 결측 {len(miss_pe)}건")

    bad_corp = [r for r in rows if not CORP_RE.match(r.get("corp") or "")]
    chk(len(bad_corp) == a["corpContractViolations"], f"corp 계약 [0-9]{{8}} (위반 {len(bad_corp)}건)")

    dup = len(rows) - len({rec_key(r) for r in rows})
    chk(dup == a["duplicateKeys"], f"(corp, fiscalYear, availableFrom, reprtCode) 중복 {dup}건")

    viol = [r for r in rows if (r.get("availableFrom") or "") <= (r.get("periodEnd") or "")]
    diag["pitContractViolationSample"] = [
        {"corp": r["corp"], "fiscalYear": r["fiscalYear"], "reprtCode": r["reprtCode"],
         "availableFrom": r["availableFrom"], "periodEnd": r["periodEnd"]} for r in viol[:20]]
    chk(len(viol) == a["pitContractViolations"],
        f"계약 availableFrom > periodEnd (위반 {len(viol)}건)")

    found = sum(1 for r in rows if r.get("istcTotqy") is not None)
    rate = found / len(rows) if rows else 0
    diag["istcTotqyRowFoundRate"] = round(rate, 5)
    warn(rate >= a["istcTotqyRowFoundRateWarn"],
         f"istc_totqy 확보율 {rate*100:.2f}% >= {a['istcTotqyRowFoundRateWarn']*100:.0f}% "
         f"({found}/{len(rows)})")

    rm = replay_metrics(rows)
    diag["replayMetrics"] = rm
    if rm["directRatio"] is not None:
        warn(rm["directRatio"] >= a["directRatioWarn"],
             f"direct 비율 {rm['directRatio']*100:.2f}% >= {a['directRatioWarn']*100:.0f}%")
    if rm["neverValidRatio"] is not None:
        warn(rm["neverValidRatio"] <= a["neverValidRateWarn"],
             f"neverValid 비율 {rm['neverValidRatio']*100:.2f}% <= {a['neverValidRateWarn']*100:.0f}%")
    warn(rm["maxConsecutiveMissing"] <= a["maxConsecutiveMissingWarn"],
         f"최대 연속 결측 {rm['maxConsecutiveMissing']} <= {a['maxConsecutiveMissingWarn']}")
    print(f"  --  동시접수 {rm['coFilingCount']}건 (게이트 아님, tieBreak가 결정론적으로 처리)")

    if from_output_only:
        diag["revalidatedFromOutputOnly"] = True
        print("  --  상태가 있어야 잴 수 있는 항목은 건너뛴다")
        return

    incomplete = diag.get("corpsIncomplete")
    chk(incomplete == a["corpsIncomplete"],
        f"미완료 법인 {incomplete}건 (담당 {diag.get('targetCorps')} · 완료 {diag.get('corpsDone')})")

    planned = diag.get("plannedCells")
    scanned = diag.get("scannedCells")
    mismatch = abs((planned or 0) - (scanned or 0)) if planned is not None else -1
    chk(mismatch == a["scannedCellsMismatch"],
        f"스캔 셀 {scanned} == 격자 셀(corp×fiscalYear×4reprt) {planned} (차 {mismatch})")

    rc_present = sum(1 for r in rows if r.get("rceptNo"))
    rc_rate = rc_present / len(rows) if rows else None
    diag["rceptNoPresentRate"] = round(rc_rate, 5) if rc_rate is not None else None
    chk(rc_rate is not None and rc_rate >= a["rceptNoPresentRateMin"],
        f"rcept_no 존재율 {rc_rate} >= {a['rceptNoPresentRateMin']}")

    af_rate = sum(1 for r in rows if DATE8.match(r.get("availableFrom") or "")) / len(rows) if rows else None
    diag["availableFromParsableRate"] = round(af_rate, 5) if af_rate is not None else None
    chk(af_rate is not None and af_rate >= a["availableFromParsableRateMin"],
        f"availableFrom 파싱율 {af_rate} >= {a['availableFromParsableRateMin']}")


# ── finalize ───────────────────────────────────────────────────
RCEPT_FAIL_REASONS = ("RCEPT_NO_MISSING", "RCEPT_NO_MALFORMED", "AVAILABLE_FROM_UNPARSED",
                      "PERIOD_END_UNPARSED")


def _merge_state(sdir, diag):
    scanned_all, done_all, calls = {}, set(), 0
    status, reasons = Counter(), Counter()
    for p in sorted(glob.glob(f"{sdir}/_state-*.json")):
        st = load_json(p)
        done_all |= set(st.get("corpsDone") or [])
        calls += st.get("callsUsedToday", 0)
        for corp, years in (st.get("scanned") or {}).items():
            scanned_all[corp] = years
            for cells in years.values():          # cells: {reprtCode: status}
                for v in cells.values():
                    status[v.split(":", 1)[0]] += 1
                    if v.startswith("REJECTED:"):
                        reasons[v.split(":", 1)[1]] += 1
    diag["scannedCells"] = sum(len(cells) for years in scanned_all.values() for cells in years.values())
    diag["scannedCorps"] = len(scanned_all)
    diag["dartStatusDistribution"] = dict(status)
    diag["rejectReasons"] = dict(reasons)
    diag["corpsDone"] = len(done_all)
    diag["callsTotal"] = calls
    return scanned_all, done_all


def run_finalize(pol):
    a3c = pol["a3c"]
    out_dir, sdir = a3c["output"]["dir"], a3c["output"]["stateDir"]
    dpath = f"{out_dir}/_diagnostics.json"
    diag = {"stage": "A3c", "mode": "finalize", "stageVersion": STAGE_VERSION,
            "fundamentalsPolicy": pol["version"]}

    shard_files = sorted(glob.glob(f"{sdir}/shard-*.jsonl"))
    if not shard_files:
        _abort(f"{sdir}에 샤드 산출물이 없다 — 수집 잡을 먼저 돌려라", diag, dpath)

    rows = []
    for p in shard_files:
        rows.extend(load_jsonl(p))
    diag["shardCount"] = len(shard_files)
    diag["rowCount"] = len(rows)
    print(f"[1/3] 샤드 {len(shard_files)}개 병합 — {len(rows)}행")
    if not rows:
        _abort("병합 결과 0행", diag, dpath)

    grid, corps, gmeta = build_grid(pol)
    diag.update(gmeta)
    diag["plannedCells"] = sum(len(v) for v in grid.values()) * len(REPRT_CODES)
    _merge_state(sdir, diag)
    diag["corpsIncomplete"] = len(grid) - diag["corpsDone"]
    print(f"[2/3] 격자 {diag['plannedCells']}셀 · 스캔 {diag['scannedCells']}셀 · "
          f"호출 {diag['callsTotal']} · 미완료 {diag['corpsIncomplete']}법인")

    validate(rows, pol, diag)
    _write_diag(diag, dpath)
    if warns:
        print(f"\nWARN {len(warns)}건:")
        for w in warns:
            print(f"  - {w}")
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 산출물을 쓰지 않는다")
        for x in fails:
            print(f"  - {x}")
        return 1

    print("\n[3/3] 연도 분할 · gzip")
    _write_years(rows, a3c["output"], diag)
    _write_diag(diag, dpath)
    print(f"\n{out_dir} — {len(rows)}행 · replay {diag['replayMetrics']}")
    return 0


def run_revalidate(pol):
    a3c = pol["a3c"]
    out_dir = a3c["output"]["dir"]
    if not a3c.get("revalidate", {}).get("enabled", True):
        print("a3c.revalidate.enabled 가 아니다")
        return 1
    rows = []
    for p in sorted(glob.glob(f"{out_dir}/*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            rows += [json.loads(l) for l in f if l.strip()]
    if not rows:
        print(f"{out_dir}에 산출물이 없다")
        return 1
    diag = {"stage": "A3c", "mode": "revalidate", "stageVersion": STAGE_VERSION,
            "fundamentalsPolicy": pol["version"], "rowCount": len(rows)}
    print(f"A3c 재판정 — {len(rows)}행 (산출물만)")
    validate(rows, pol, diag, from_output_only=True)
    _write_diag(diag, f"{out_dir}/_revalidate.json")
    print(f"\n{'통과' if not fails else '실패 ' + str(len(fails)) + '건'} · WARN {len(warns)}건")
    return 0 if not fails else 1


def _write_years(rows, out, diag):
    os.makedirs(out["dir"], exist_ok=True)
    for old in glob.glob(f"{out['dir']}/*.jsonl.gz"):
        os.remove(old)
    key = out["sortKey"]
    rows.sort(key=lambda r: tuple(str(r[k]) for k in key))
    by_year = defaultdict(list)
    for r in rows:
        by_year[str(r["fiscalYear"])].append(r)
    years = {}
    for y in sorted(by_year):
        payload = [{k: r.get(k) for k in out["fields"]} for r in by_year[y]]
        raw = "".join(json.dumps(x, ensure_ascii=False) + "\n"
                      for x in payload).encode("utf-8")
        p = f"{out['dir']}/{y}.jsonl.gz"
        with gzip.GzipFile(p, "wb", compresslevel=out["gzipCompressLevel"],
                           mtime=out["gzipMtime"]) as f:
            f.write(raw)
        years[y] = {"rows": len(payload), "gzBytes": os.path.getsize(p)}
        print(f"  {y}.jsonl.gz  {len(payload):>7}행")
    diag["years"] = years


def _write_diag(diag, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int)
    ap.add_argument("--shards", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--revalidate", action="store_true")
    ap.add_argument("--plan", action="store_true",
                    help="네트워크 없이 격자만 계산해 출력한다")
    ap.add_argument("--limit", type=int, default=0,
                    help="스모크 테스트용. 진단에 smokeTest 플래그가 박힌다")
    args = ap.parse_args()

    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음")
        return 1
    pol = load_json(POLICY)
    if "a3c" not in pol:
        print(f"{POLICY}({pol.get('version')})에 a3c 블록이 없다 — FN-1.6 이상이 필요하다")
        return 1

    if args.plan:
        grid, corps, meta = build_grid(pol)
        meta["plannedCells"] = sum(len(v) for v in grid.values()) * len(REPRT_CODES)
        meta["plannedCorps"] = len(grid)
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0
    if args.revalidate:
        return run_revalidate(pol)
    if args.finalize:
        return run_finalize(pol)
    if args.shard is None:
        print("--shard N --shards M · --finalize · --revalidate · --plan 중 하나가 필요하다")
        return 1
    shards = args.shards or pol["a3c"].get("shards") or pol["shards"]
    if not (0 <= args.shard < shards):
        print(f"--shard는 0 이상 {shards} 미만이어야 한다")
        return 1
    return run_shard(args.shard, shards, pol, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
