#!/usr/bin/env python3
"""A3b — 배당·주당순이익 (FN-1.5)

계약은 `docs/A3b-1.0-배당EPS계약.md`, 정의는 `config/policies/fundamentals.v1.json`의
`a3b` 블록이 단일 산출점이다. **이 스크립트에 소스·격자·임계를 하드코딩하지 않는다** —
회귀(`test-fundamentals-a3b.py`)가 그것을 강제한다.

A3의 복사에 가깝다. **그대로 복사하면 안 되는 곳이 넷**이고, A3와 다른 코드는 전부
그 넷 중 하나다.

  1. 격자를 A3 산출물에서 읽는다
     A3가 보고서를 찾은 (corp, fiscalYear)만 조회한다. A3의 공백 7,326셀을 다시
     두드리지 않는다. 그리고 A3 데이터가 없는 법인은 조기 종료로 따로 스캔한다 —
     그 안에 현재 상장 15법인이 있고 그들이 목표 집단이다.
  2. 스캔한 셀은 결과가 없어도 남긴다
     A3는 빈 gaps를 pop해서 798법인 중 599의 '조회 여부'가 기록에 없다. 그 실수를
     반복하지 않는다 — '조회하지 않음'과 '조회했더니 없음'은 다르다(교훈75).
  3. 배당은 세 갈래다
     행 있음·값 숫자 / 행 있음·값 없음(무배당, 0) / 행 없음(결측, null).
     0과 null을 합치면 배당 안 주는 회사가 전부 유보가 된다. 판정은 A5가 한다.
  4. periodEnd는 stlm_dt다
     A3의 thstrm_dt가 아니다. 다른 엔드포인트라 필드가 다르고, 정찰이 실측했다.

일 예산·샤드 배분은 A3의 `shard_budget()`을 **가져다 쓴다.** 복사하면 정책은 하나인데
구현이 둘이 된다.

  --shard N --shards M   담당 법인 수집 → _shards_a3b/shard-N.jsonl (Actions가 커밋)
  --finalize             병합 → 인수 조건 → 연도 분할 → gzip
  --revalidate           커밋된 산출물만으로 인수 조건 재판정 (계약 §9)
  --plan                 네트워크 없이 격자만 계산해 출력한다

입력:
  config/policies/fundamentals.v1.json      a3b 블록
  data/backfill/universe/a1a/current.jsonl  · a1b/delisted.jsonl
  data/backfill/fundamentals/a3/*.jsonl.gz  격자와 rceptNo 대조의 출처
출력:
  data/backfill/fundamentals/a3b/{YYYY}.jsonl.gz
  data/backfill/fundamentals/a3b/_diagnostics.json
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
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")

STAGE_VERSION = "A3b.0"
TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
CORP_RE = re.compile(r"^[0-9]{8}$")
DATE8 = re.compile(r"^\d{8}$")
RCEPT14 = re.compile(r"^\d{14}$")
DT_IN_TEXT = re.compile(r"(\d{4})[.\-/]?(\d{2})[.\-/]?(\d{2})")

fails, warns = [], []


def _load_a3():
    """A3 모듈에서 순수 함수만 가져온다(예산 배분·HTTP 규약·날짜).

    파일명에 하이픈이 있어 import 문으로는 못 읽는다. A3 모듈의 최상위는 상수·함수
    정의뿐이라 부작용이 없다. A3b는 자기 fails/warns를 따로 들고 있다.
    """
    spec = importlib.util.spec_from_file_location(
        "a3", os.path.join(ROOT, "scripts", "build-fundamentals-a3.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


A3 = _load_a3()

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
    """실패해도 진단은 남긴다(교훈39)."""
    diag.update({"aborted": True, "abortReason": reason, **(extra or {})})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    sys.exit(2)


# ── DART ───────────────────────────────────────────────────────
DART_NO_DATA = "013"


def dart_get(endpoint, params, pol=None):
    """(json, dartStatus, error). 키는 로그·산출물에 절대 넣지 않는다.

    DART는 조회 실패도 HTTP 200 + status 필드로 준다 — HTTP만 보는 재시도는 013·020에서
    한 번도 돌지 않는다. 두 축을 다 본다.

    **재시도가 필요한 이유**: 재시도 없이 일시 오류를 그대로 돌려주면 호출부가 그것을
    '빈 응답'으로 세고, 두 번 연속이면 조기 종료가 걸려 **그 법인이 데이터 없이 완료로
    들어간다.** 네트워크 한 번 튄 것이 영구 결측이 되는 경로다(A3의 done.add 결함과
    같은 모양). 013과 한도(020)는 재시도하지 않는다 — 답이 바뀌지 않는다.
    """
    attempts = (pol or {}).get("retryAttempts", 1)
    base = (pol or {}).get("retryBackoffBase", 2)
    quota_status = ((pol or {}).get("quota") or {}).get("quotaExceededStatus", "020")
    last = (None, "unknown", "unknown")
    for i in range(attempts):
        try:
            r = requests.get(f"{BASE}/{endpoint}", params={"crtfc_key": KEY, **params})
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
                    # 답이 바뀌지 않는 둘은 즉시 돌려준다
                    if st in (DART_NO_DATA, quota_status):
                        return None, st, str(j.get("message", ""))[:150]
                    last = (None, st, str(j.get("message", ""))[:150])
        if i < attempts - 1:
            time.sleep(base ** i)
    return last


# ── 파싱 (순수 함수 — 회귀가 여기를 밟는다) ────────────────────────
def _norm(x):
    return str(x or "").replace(" ", "")


def parse_amount(raw):
    """(value, kind). kind는 'numeric' | 'empty' | 'unparsable'.

    빈 값과 못 읽는 값을 갈라야 배당 세 갈래가 성립한다 — 둘을 합치면 무배당과
    파싱 실패가 같은 모양이 된다.
    """
    s = str(raw if raw is not None else "").strip()
    if s in ("", "-", "－", "N/A"):
        return None, "empty"
    neg = s.startswith("-") or (s.startswith("△"))
    t = s.lstrip("-△").replace(",", "").strip()
    if not t or not t.replace(".", "", 1).isdigit():
        return None, "unparsable"
    v = float(t) if "." in t else int(t)
    return (-v if neg else v), "numeric"


def pick_row(rows, prefs, stock_knd_prefs=None):
    """se 라벨 선별. 정책의 우선순위 배열을 그대로 쓴다(하드코딩 금지)."""
    for p in prefs:
        cands = [r for r in rows if _norm(p) in _norm(r.get("se"))]
        if not cands:
            continue
        if stock_knd_prefs:
            for k in stock_knd_prefs:
                hit = [r for r in cands if _norm(k) in _norm(r.get("stock_knd"))]
                if hit:
                    return hit[0], p
        return cands[0], p
    return None, None


def parse_period_end(rows, field):
    """stlm_dt에서 회계기간말. 형태를 가정하지 않고 마지막 날짜를 캔다.

    정찰 실측은 'YYYY-MM-DD' 단일값 28/28이었지만 한 번의 관측을 성질로 읽지 않는다 —
    A3의 thstrm_dt는 '2023.12.31 현재' 같은 문장형이었다.
    """
    for raw in sorted({str(r.get(field) or "") for r in rows}, reverse=True):
        found = DT_IN_TEXT.findall(raw)
        if found:
            return "".join(found[-1])
    return None


def build_record(corp, ticker, year, rows, a3b):
    """응답 → 레코드 또는 (None, 사유). 계약 §5의 세 갈래가 여기서 만들어진다."""
    src, pit, div = a3b["source"], a3b["pointInTime"], a3b["dividend"]

    rcepts = sorted({str(r.get("rcept_no") or "") for r in rows if r.get("rcept_no")})
    if not rcepts:
        return None, "RCEPT_NO_MISSING"
    rc = rcepts[-1]
    if not RCEPT14.match(rc):
        return None, "RCEPT_NO_MALFORMED"
    available_from = rc[:8]
    if not DATE8.match(available_from):
        return None, "AVAILABLE_FROM_UNPARSED"

    period_end = parse_period_end(rows, pit["periodEndSource"])
    if not period_end:
        return None, "PERIOD_END_UNPARSED"

    eps_row, eps_src = pick_row(rows, src["epsPreference"])
    eps, eps_kind = (None, "absent")
    if eps_row is not None:
        eps, eps_kind = parse_amount(eps_row.get("thstrm"))
        # eps는 배당과 다르다 — 빈 값을 0으로 읽으면 '주당순이익 0'과 섞인다.
        if eps_kind != "numeric":
            eps = None

    div_row, _ = pick_row(rows, src["dividendPreference"],
                          src.get("dividendStockKndPreference"))
    if div_row is None:
        div_present, dps = False, None
    else:
        div_present = True
        val, kind = parse_amount(div_row.get("thstrm"))
        # ★ 계약 §5.1 — 행이 있는데 값이 비면 무배당이고 그것은 관측된 사실(0)이다.
        #   결측(null)과 합치면 배당 안 주는 회사가 전부 유보가 된다.
        if kind == "numeric":
            dps = val
        elif kind == "empty" and div.get("semantics") == "threeWay":
            dps = 0
        else:
            dps = None

    return {
        "corp": corp,
        "ticker": ticker,
        "fiscalYear": year,
        "availableFrom": available_from,
        "rceptNo": rc,
        "periodEnd": period_end,
        "eps": eps,
        "epsSource": eps_src,
        "dividendRowPresent": div_present,
        "dividendPerShare": dps,
        "dividendStockKnd": (_norm(div_row.get("stock_knd")) if div_row else None),
    }, None


# ── 격자 (네트워크 없음 — --plan 으로 따로 볼 수 있다) ──────────────
A3_DIR = "data/backfill/fundamentals/a3"


def a3_grid():
    """A3 산출물의 (corp, fiscalYear) → 그 셀의 최신 rceptNo. 격자이자 대조 기준선."""
    out = {}
    for p in sorted(glob.glob(f"{A3_DIR}/*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                k = (r["corp"], r["fiscalYear"])
                if k not in out or r["availableFrom"] > out[k]["availableFrom"]:
                    out[k] = {"rceptNo": r.get("rceptNo"),
                              "availableFrom": r["availableFrom"]}
    return out


def target_corps():
    """corp → {ticker, group}. A1a·A1b가 단일 출처다."""
    out = {}
    for r in load_jsonl(A1B):
        if r.get("corp"):
            out[r["corp"]] = {"ticker": r.get("ticker"), "group": "delisted"}
    for r in load_jsonl(A1A):
        if r.get("corp"):
            out[r["corp"]] = {"ticker": r.get("ticker"), "group": "current"}
    return out


def build_grid(pol):
    """(corp → [연도...], meta). 계약 §3의 두 갈래를 여기서 만든다."""
    a3b = pol["a3b"]
    mode = a3b["grid"]["mode"]
    if mode != "a3ReuseAndScanMissing":
        # 모르는 값을 조용히 폴백시키지 않는다. 폴백은 느슨해지는 방향의 우회다.
        raise ValueError(f"a3b.grid.mode '{mode}' — 허용값은 a3ReuseAndScanMissing 뿐이다")

    corps = target_corps()
    grid_src = a3_grid()
    years_all = list(range(pol["fiscalYearFrom"], pol["fiscalYearTo"] + 1))

    reuse = defaultdict(list)
    for (c, y) in grid_src:
        if c in corps:
            reuse[c].append(y)
    for c in reuse:
        reuse[c].sort()

    # A3 데이터가 없는 법인. 조기 종료가 걸리므로 전 연도를 넣어도 실제 호출은 2~3건이다.
    missing = sorted(set(corps) - set(reuse))
    grid = {c: list(ys) for c, ys in reuse.items()}
    if a3b["grid"].get("scanMissingCorps"):
        for c in missing:
            grid[c] = list(years_all)

    meta = {
        "gridMode": mode,
        "reuseCorps": len(reuse),
        "reuseCells": sum(len(v) for v in reuse.values()),
        "missingCorps": len(missing),
        "missingCorpsByGroup": dict(Counter(corps[c]["group"] for c in missing)),
        "missingCellsUpperBound": len(missing) * len(years_all),
        "targetCorps": len(corps),
    }
    return grid, corps, grid_src, meta


# ── 수집 ───────────────────────────────────────────────────────
def scan_corp(corp, ticker, years, pol, state, counters):
    """(records, scanned, quota_hit). scanned는 조회한 셀 전부다 — 결과가 없어도 남긴다(§7).

    ★ 한도(020)를 만나면 **이 법인을 통째로 버리고 quota_hit 을 올린다.** 빈 응답으로
    세면 안 된다 — 두 번 연속이면 조기 종료가 걸려 그 법인이 데이터 없이 완료로
    들어가고, 그 결측은 재수집 없이는 영영 안 채워진다. 여기까지 모은 공백 사유도
    부분이라 함께 버린다: 반쪽 사실을 남기면 다음 실행의 온전한 사실과 섞인다
    (A3의 같은 자리와 동일한 규율).
    """
    a3b = pol["a3b"]
    stop_after = pol["stopAfterConsecutiveEmptyYears"]
    quota_status = pol["quota"]["quotaExceededStatus"]
    recs, scanned = [], {}
    consec_empty = 0

    for y in years:
        if consec_empty >= stop_after:
            # 조기 종료. '조회하지 않았다'를 남기지 않는다 — 남기면 013과 섞인다.
            break
        j, st, err = dart_get(a3b["source"]["endpoint"], {
            "corp_code": corp, "bsns_year": str(y),
            "reprt_code": a3b["source"]["reprtCode"]}, pol)
        counters["calls"] += 1
        state["callsUsedToday"] += 1
        if st == quota_status:
            counters["quotaHits"] += 1
            return [], {}, True
        rows = (j or {}).get("list") or []
        if st != "000" or not rows:
            scanned[str(y)] = st if st != "000" else "EMPTY"
            consec_empty += 1
            counters["emptyCells"] += 1
            continue
        rec, why = build_record(corp, ticker, y, rows, a3b)
        if rec is None:
            scanned[str(y)] = f"REJECTED:{why}"
            counters["rejected"][why] += 1
            consec_empty = 0
            continue
        scanned[str(y)] = "OK"
        recs.append(rec)
        consec_empty = 0
        time.sleep(pol["requestSleepSeconds"])

    if consec_empty >= stop_after:
        remaining = [y for y in years if str(y) not in scanned]
        for y in remaining:
            scanned[str(y)] = "EARLY_STOP"
    return recs, scanned, False


def rec_key(r):
    return (r["corp"], r["fiscalYear"], r["availableFrom"])


def run_shard(shard, shards, pol, limit):
    a3b = pol["a3b"]
    out = a3b["output"]
    sdir = out["stateDir"]
    os.makedirs(sdir, exist_ok=True)
    spath = f"{sdir}/_state-{shard}.json"
    dpath = f"{sdir}/_diagnostics-shard-{shard}.json"
    today = A3.today_kst()

    diag = {"stage": "A3b", "mode": "shard", "shard": shard, "shards": shards,
            "stageVersion": STAGE_VERSION, "fundamentalsPolicy": pol["version"],
            "runDate": today}

    if not KEY:
        _abort("DART_API_KEY 없음", diag, dpath)

    grid, corps, grid_src, gmeta = build_grid(pol)
    diag.update(gmeta)
    mine = sorted(grid)[shard::shards]
    if limit:
        mine = mine[:limit]
        diag["smokeTest"] = True

    state = load_json(spath) if os.path.exists(spath) else {
        "shard": shard, "corpsDone": [], "scanned": {},
        "callsUsedToday": 0, "lastRunDate": None, "corpsAssigned": 0}
    if state.get("lastRunDate") != today:
        state["callsUsedToday"] = 0          # DART 한도는 KST 하루 단위다
        state["lastRunDate"] = today
    state["corpsAssigned"] = len(mine)

    budget, bdetail = A3.shard_budget(pol, shards, shard, state["callsUsedToday"],
                                      today, state_dir=sdir)
    diag["shardBudget"] = bdetail

    done = set(state["corpsDone"])
    todo = [c for c in mine if c not in done]
    print(f"A3b 샤드 {shard}/{shards} — 담당 {len(mine)}법인 · 완료 {len(mine)-len(todo)} "
          f"· 남음 {len(todo)}")
    print(f"  격자 {gmeta['reuseCells']}셀 재사용 + 미확보 {gmeta['missingCorps']}법인 "
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
            # done 에 넣지 않는다. 넣으면 그 법인이 영구히 건너뛰어지고, 완료 게이트가
            # 그것을 완료로 계산해 빈 데이터가 인수 조건을 그대로 지나간다.
            quota_hit = True
            break
        for r in recs:
            records[rec_key(r)] = r
        # ★ 계약 §7 — 결과가 없어도 남긴다. 빈 dict 도 남긴다.
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
    return 0          # 예산 소진은 실패가 아니다


# ── 인수 조건 ──────────────────────────────────────────────────
def validate(rows, pol, diag, grid_src, corps, from_output_only=False):
    a = pol["a3b"]["acceptance"]
    print("\n[인수 조건]")

    inject = os.environ.get("A3B_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    bad_date = [r for r in rows if not DATE8.match(r.get("availableFrom") or "")
                or not DATE8.match(r.get("periodEnd") or "")]
    chk(len(bad_date) == a["dateContractViolations"],
        f"날짜 계약 YYYYMMDD (위반 {len(bad_date)}건)")

    miss_af = [r for r in rows if not r.get("availableFrom")]
    chk(len(miss_af) == a["availableFromMissing"], f"availableFrom 결측 {len(miss_af)}건")
    miss_pe = [r for r in rows if not r.get("periodEnd")]
    chk(len(miss_pe) == a["periodEndMissing"], f"periodEnd 결측 {len(miss_pe)}건")

    bad_corp = [r for r in rows if not CORP_RE.match(r.get("corp") or "")]
    chk(len(bad_corp) == a["corpContractViolations"],
        f"corp 계약 [0-9]{{8}} (위반 {len(bad_corp)}건)")

    dup = len(rows) - len({rec_key(r) for r in rows})
    chk(dup == a["duplicateKeys"], f"(corp, fiscalYear, availableFrom) 중복 {dup}건")

    # 계약 1 — 공시는 회계기간말 뒤에 나온다. 뒤집히면 백테스트에 look-ahead 가 들어간다.
    viol = [r for r in rows if (r.get("availableFrom") or "") <= (r.get("periodEnd") or "")]
    diag["pitContractViolationSample"] = [
        {"corp": r["corp"], "fiscalYear": r["fiscalYear"],
         "availableFrom": r["availableFrom"], "periodEnd": r["periodEnd"]}
        for r in viol[:20]]
    chk(len(viol) == a["pitContractViolations"],
        f"계약 1 availableFrom > periodEnd (위반 {len(viol)}건)")

    # 배당 세 갈래 분포. 게이트가 아니라 구성 사실이다(계약 §8).
    three = Counter()
    for r in rows:
        if not r.get("dividendRowPresent"):
            three["absent"] += 1
        elif r.get("dividendPerShare") == 0:
            three["zeroNoDividend"] += 1
        elif r.get("dividendPerShare") is None:
            three["presentUnparsable"] += 1
        else:
            three["numeric"] += 1
    diag["dividendThreeWayDistribution"] = dict(three)

    eps_num = sum(1 for r in rows if r.get("eps") is not None)
    eps_rate = eps_num / len(rows) if rows else 0
    diag["epsNumericRate"] = round(eps_rate, 5)
    warn(eps_rate >= a["epsNumericRateWarn"],
         f"eps 숫자 비율 {eps_rate*100:.2f}% >= {a['epsNumericRateWarn']*100:.0f}% "
         f"({eps_num}/{len(rows)})")

    cur = {c for c, v in corps.items() if v["group"] == "current"}
    cur_with = {r["corp"] for r in rows if r.get("eps") is not None} & cur
    cur_rate = len(cur_with) / len(cur) if cur else 0
    diag["currentListedEpsRate"] = round(cur_rate, 5)
    diag["currentListedCorps"] = len(cur)
    warn(cur_rate >= a["currentListedEpsRateWarn"],
         f"현재 상장 eps 확보율 {cur_rate*100:.2f}% >= "
         f"{a['currentListedEpsRateWarn']*100:.0f}% ({len(cur_with)}/{len(cur)})")

    # A3 rceptNo 대조. 다르면 두 실행 사이의 정정공시이고 결함이 아니다(계약 §4).
    same = diff = 0
    for r in rows:
        a3 = grid_src.get((r["corp"], r["fiscalYear"]))
        if a3 and a3.get("rceptNo"):
            if str(a3["rceptNo"]) == r["rceptNo"]:
                same += 1
            else:
                diff += 1
    diag["rceptNoVsA3"] = {"same": same, "amended": diff}

    if from_output_only:
        diag["revalidatedFromOutputOnly"] = True
        print("  --  상태가 있어야 잴 수 있는 항목은 건너뛴다 (계약 §9)")
        return

    # 상태가 있어야 잴 수 있는 것들 — 산출물에 없는 행은 이유를 말하지 않는다(교훈75).
    #
    # 전 샤드가 담당분을 끝냈는가부터 본다. 예산 소진으로 중단된 샤드가 섞이면 부분
    # 수집물에 manifest 가 찍히고, manifest 는 '인수 조건을 통과했다'는 뜻이다(교훈43).
    # 아래 스캔 셀 대조가 간접적으로 잡지만 그 메시지는 원인을 말하지 못한다.
    incomplete = diag.get("corpsIncomplete")
    chk(incomplete == a["corpsIncomplete"],
        f"미완료 법인 {incomplete}건 (담당 {diag.get('targetCorps')} · "
        f"완료 {diag.get('corpsDone')})")

    planned = diag.get("plannedCells")
    scanned = diag.get("scannedCells")
    mismatch = abs((planned or 0) - (scanned or 0)) if planned is not None else -1
    chk(mismatch == a["scannedCellsMismatch"],
        f"스캔 셀 {scanned} == 격자 셀 {planned} (차 {mismatch})")

    rc_rate = diag.get("rceptNoPresentRate")
    chk(rc_rate is not None and rc_rate >= a["rceptNoPresentRateMin"],
        f"rcept_no 존재율 {rc_rate} >= {a['rceptNoPresentRateMin']} "
        f"(분모는 행이 돌아온 {diag.get('respondedCells')}셀 — 013은 빠진다)")


# ── finalize ───────────────────────────────────────────────────
# rcept_no 를 못 얻어 레코드를 버린 사유. 나머지 REJECTED 는 rcept_no 가 있었는데
# 다른 이유로 버린 것이라 이 비율의 분자에서 빼면 안 된다.
RCEPT_FAIL_REASONS = ("RCEPT_NO_MISSING", "RCEPT_NO_MALFORMED", "AVAILABLE_FROM_UNPARSED")


def _merge_state(sdir, diag):
    scanned_all, done_all, calls = {}, set(), 0
    status, reasons = Counter(), Counter()
    for p in sorted(glob.glob(f"{sdir}/_state-*.json")):
        st = load_json(p)
        done_all |= set(st.get("corpsDone") or [])
        calls += st.get("callsUsedToday", 0)
        for corp, cells in (st.get("scanned") or {}).items():
            scanned_all[corp] = cells
            for v in cells.values():
                status[v.split(":", 1)[0]] += 1
                if v.startswith("REJECTED:"):
                    reasons[v.split(":", 1)[1]] += 1
    diag["scannedCells"] = sum(len(v) for v in scanned_all.values())
    diag["scannedCorps"] = len(scanned_all)
    diag["dartStatusDistribution"] = dict(status)
    diag["rejectReasons"] = dict(reasons)
    diag["corpsDone"] = len(done_all)
    diag["callsTotal"] = calls

    # ★ 분모는 '스캔한 셀'이 아니라 '행이 돌아온 셀'이다. 보고서가 없는 013·EARLY_STOP 을
    #   분모에 넣으면 '보고서가 없다'가 'rcept_no 를 안 준다'로 읽힌다 — 이 게이트가
    #   재려는 것은 후자뿐이다. 실측 격자에서 013 이 8,778셀이라 그 혼동은 0.74 대 1.0의
    #   차이이고, 2일 수집 뒤 finalize 에서 하드 FAIL 로 나타났을 것이다(교훈57).
    responded = status.get("OK", 0) + status.get("REJECTED", 0)
    rcept_fail = sum(reasons.get(r, 0) for r in RCEPT_FAIL_REASONS)
    diag["respondedCells"] = responded
    diag["rceptNoPresentRate"] = (round((responded - rcept_fail) / responded, 5)
                                  if responded else None)
    return scanned_all, done_all


def run_finalize(pol):
    a3b = pol["a3b"]
    out_dir, sdir = a3b["output"]["dir"], a3b["output"]["stateDir"]
    dpath = f"{out_dir}/_diagnostics.json"
    diag = {"stage": "A3b", "mode": "finalize", "stageVersion": STAGE_VERSION,
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

    grid, corps, grid_src, gmeta = build_grid(pol)
    diag.update(gmeta)
    diag["plannedCells"] = sum(len(v) for v in grid.values())
    _merge_state(sdir, diag)
    # 담당 법인 전체를 분모로 센다. 샤드별 상태만 보면 아예 안 돈 샤드가 안 보인다 —
    # 그 샤드의 법인은 어느 corpsDone 에도 없으므로 여기서만 드러난다(교훈73의 M 자리).
    diag["corpsIncomplete"] = len(grid) - diag["corpsDone"]
    print(f"[2/3] 격자 {diag['plannedCells']}셀 · 스캔 {diag['scannedCells']}셀 · "
          f"호출 {diag['callsTotal']} · 미완료 {diag['corpsIncomplete']}법인")

    validate(rows, pol, diag, grid_src, corps)
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
    _write_years(rows, a3b["output"], diag)
    _write_diag(diag, dpath)
    print(f"\n{out_dir} — {len(rows)}행 · 배당 {diag['dividendThreeWayDistribution']}")
    return 0


def run_revalidate(pol):
    """커밋된 산출물만으로 재판정한다(계약 §9). 상태가 필요한 항목은 건너뛴다."""
    a3b = pol["a3b"]
    out_dir = a3b["output"]["dir"]
    if not a3b.get("revalidate", {}).get("enabled"):
        print("a3b.revalidate.enabled 가 아니다")
        return 1
    rows = []
    for p in sorted(glob.glob(f"{out_dir}/*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            rows += [json.loads(l) for l in f if l.strip()]
    if not rows:
        print(f"{out_dir}에 산출물이 없다")
        return 1
    _, corps, grid_src, _ = build_grid(pol)
    diag = {"stage": "A3b", "mode": "revalidate", "stageVersion": STAGE_VERSION,
            "fundamentalsPolicy": pol["version"], "rowCount": len(rows)}
    print(f"A3b 재판정 — {len(rows)}행 (산출물만)")
    validate(rows, pol, diag, grid_src, corps, from_output_only=True)
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
    if "a3b" not in pol:
        print(f"{POLICY}({pol.get('version')})에 a3b 블록이 없다 — FN-1.5 이상이 필요하다")
        return 1

    if args.plan:
        grid, corps, _, meta = build_grid(pol)
        meta["plannedCells"] = sum(len(v) for v in grid.values())
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
    shards = args.shards or pol["a3b"].get("shards") or pol["shards"]
    if not (0 <= args.shard < shards):
        print(f"--shard는 0 이상 {shards} 미만이어야 한다")
        return 1
    return run_shard(args.shard, shards, pol, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
