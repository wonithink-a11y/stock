#!/usr/bin/env python3
"""A3 — 재무 (PIT) 백필 (BF-1.1)

A1a 2,579 + A1b 1,222 = 3,801개 법인의 연간 재무제표를 DART에서 받아 사업연도별로
나눠 저장한다. 정의는 config/policies/fundamentals.v1.json(FN-1.0)이 단일 산출점이다.

A3의 본질은 재무 수치가 아니라 시점이다. 운영 수집기(scripts/fetch-fundamentals-kr.js)는
'현재 값'을 쓰고, 여기는 '그 시점에 알 수 있었던 값'을 쓴다. 그 축이 availableFrom이고,
availableFrom > periodEnd가 성립하지 않으면 백테스트에 look-ahead가 들어간다.

두 모드로 돈다. A2a와 같은 이유(실행 축과 저장 축의 분리)에 더해, A3에는 이유가 하나 더
있다 — DART 일 한도 20,000건이라 수집이 여러 날에 걸친다.

  --shard N --shards M   법인 부분집합 수집 → _shards/shard-N.jsonl (+ resume 상태)
  --finalize             전 샤드 병합 → 정렬 → 사업연도 분할 → gzip → 인수 조건 → 산출

resume이 A2a와 다른 점: A2a의 샤드는 한 실행 안에서 artifact로 넘겼지만, A3는 실행이
날짜를 넘기므로 artifact로 이어받을 수 없다. 그래서 _shards/를 Actions가 커밋하고,
finalize가 성공하면 지운다.

입력:
  config/policies/fundamentals.v1.json
  data/backfill/universe/a1a/current.jsonl    대상 법인 (A1a)
  data/backfill/universe/a1b/delisted.jsonl   대상 법인 (A1b)
출력:
  data/backfill/fundamentals/a3/{YYYY}.jsonl.gz
  data/backfill/fundamentals/a3/_diagnostics.json
"""
import argparse
import glob
import gzip
import io
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

import requests

POLICY = "config/policies/fundamentals.v1.json"
A1A = "data/backfill/universe/a1a/current.jsonl"
A1B = "data/backfill/universe/a1b/delisted.jsonl"
OUT_DIR = "data/backfill/fundamentals/a3"
SHARD_DIR = "data/backfill/fundamentals/_shards"
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")
KST = timezone(timedelta(hours=9))
STAGE_VERSION = "A3.0"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE8_RE = re.compile(r"^\d{8}$")
CORP_RE = re.compile(r"^[0-9]{8}$")
TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
# thstrm_dt는 "2023.01.01 ~ 2023.12.31"과 "2023.12.31 현재" 두 형태로 온다.
# 회계기간말은 어느 쪽이든 마지막 날짜다.
DT_IN_TEXT = re.compile(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})")

# 013(조회된 데이터 없음)은 실패가 아니다 — 그 법인이 그 해에 보고서를 안 냈다는 정상 사실이다.
# 여기 넣으면 폐지 법인 구간에서 서킷 브레이커가 즉시 열린다.
DART_NO_DATA = "013"

fails, warns = [], []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


def _abort(reason, diag, path, extra=None):
    """실패해도 진단은 남긴다(교훈39). 중단 경로도 산출이다."""
    diag.update({"aborted": True, "abortReason": reason, **(extra or {})})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    sys.exit(2)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def today_kst():
    return datetime.now(KST).strftime("%Y-%m-%d")


# ── DART 호출 ──────────────────────────────────────────────────
_orig_send = requests.adapters.HTTPAdapter.send


def _send(self, request, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = (10, 60)
    return _orig_send(self, request, **kw)


requests.adapters.HTTPAdapter.send = _send

LAST_HTTP = {"endpoint": None, "httpStatus": None, "dartStatus": None, "bytes": None}


def dart_call(endpoint, params, pol, counters):
    """(rows, dartStatus, hardError)

    DART는 조회 실패도 HTTP 200 + status 필드로 돌려준다 — HTTP status만 보는 재시도는
    0회 돈다(교훈38). 그래서 두 축을 다 보고, 재시도는 '하드 실패'에만 건다.
    '데이터 없음'을 재시도하면 폐지 법인 구간에서 호출 예산을 헛되이 태운다.

    crtfc_key는 params로만 넘기고 로그·산출물 어디에도 남기지 않는다.
    """
    last_status, last_err = None, None
    for i in range(pol["retryAttempts"]):
        counters["calls"] += 1
        try:
            r = requests.get(f"{BASE}/{endpoint}", params={"crtfc_key": KEY, **params})
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {str(e)[:150]}"
            LAST_HTTP.update(endpoint=endpoint, httpStatus=None, dartStatus=None, bytes=None)
        else:
            body = r.content or b""
            LAST_HTTP.update(endpoint=endpoint, httpStatus=r.status_code, bytes=len(body))
            if 200 <= r.status_code < 300:
                try:
                    j = r.json()
                except Exception as e:  # noqa: BLE001
                    last_err = f"PARSE {type(e).__name__}: {str(e)[:150]}"
                else:
                    st = str(j.get("status", ""))
                    LAST_HTTP["dartStatus"] = st
                    counters["dartStatus"][st] += 1
                    if st == "000":
                        return (j.get("list") or []), st, None
                    # 데이터 없음과 한도 초과는 재시도 대상이 아니다.
                    # 전자는 정상 사실이고 후자는 기다린다고 풀리지 않는다.
                    if st in (DART_NO_DATA, pol["quota"]["quotaExceededStatus"]):
                        return [], st, None
                    last_status, last_err = st, str(j.get("message", ""))[:150]
            else:
                last_err = f"HTTP {r.status_code}"
        if i < pol["retryAttempts"] - 1:
            time.sleep(pol["retryBackoffBase"] ** i)
    return [], last_status, (last_err or "unknown")


# ── 계정 매칭 ──────────────────────────────────────────────────
def id_tail(account_id):
    """'ifrs-full_Equity' · 'ifrs_Equity' → 'Equity'.

    2019년 전후로 IFRS 태그 접두사가 바뀌었다. 접두사째 비교하면 옛 사업연도가
    통째로 미매칭으로 잡히고, 그 결과가 '그 해에 소스가 무너졌다'로 오독된다.
    """
    s = (account_id or "").strip()
    if not s or s.startswith("-"):     # '-표준계정코드 미사용-'
        return None
    return s.split("_", 1)[1] if "_" in s else s


def to_amount(raw):
    if raw is None:
        return None
    t = str(raw).replace(",", "").strip()
    if not t or t == "-":
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def match_accounts(rows, spec_all, order):
    """(값, 매칭수단). 어느 수단으로 잡았는지를 남기는 이유는 계약 2다 —
    연도별 매칭률이 떨어졌을 때 소스 변화인지 이름 변주인지 사후에 갈라야 한다."""
    vals, how = {}, {}
    for key, spec in spec_all.items():
        cand = [r for r in rows if str(r.get("sj_div", "")) in spec["sj"]] or rows
        found_row, found_how = None, None
        for mode in order:
            if mode == "id":
                tails = set(spec["idTails"])
                for r in cand:
                    if id_tail(r.get("account_id")) in tails:
                        found_row, found_how = r, "id"
                        break
            elif mode == "nameExact":
                ex = set(spec["exact"])
                for r in cand:
                    if str(r.get("account_nm", "")).replace(" ", "") in ex:
                        found_row, found_how = r, "nameExact"
                        break
            elif mode == "nameContains":
                for r in cand:
                    nm = str(r.get("account_nm", "")).replace(" ", "")
                    if any(c in nm for c in spec["contains"]):
                        found_row, found_how = r, "nameContains"
                        break
            if found_row is not None:
                break
        # 계정은 잡혔는데 금액이 비어 있는 경우가 있다. 그때 매칭수단을 남기면
        # '잡았다'로 집계되어 커버리지가 실제보다 높아진다 — 값이 없으면 미매칭이다.
        amt = to_amount(found_row.get("thstrm_amount")) if found_row is not None else None
        vals[key] = amt
        how[key] = found_how if amt is not None else None
    return vals, how


def parse_period_end(rows):
    """보고서가 스스로 말하는 회계기간말. 결산월로 계산하지 않는 이유는
    결산월 변경 이력과 어긋나고, A1b 폐지 법인에는 그 필드가 아예 없기 때문이다."""
    for r in rows:
        for field in ("thstrm_dt", "thstrm_nm"):
            hits = DT_IN_TEXT.findall(str(r.get(field, "")))
            if hits:
                y, m, d = hits[-1]
                return f"{y}-{m}-{d}"
    return None


def build_record(corp, ticker, year, rows, fs_div, sic, pol):
    rcept = str(rows[0].get("rcept_no", "")).strip()
    if not DATE8_RE.match(rcept[:8]):
        return None, "RCEPT_NO_NOT_DATE"
    period_end = parse_period_end(rows)
    if not period_end:
        return None, "PERIOD_END_UNPARSED"

    vals, how = match_accounts(rows, pol["accounts"]["spec"], pol["accounts"]["matchOrder"])
    rec = {
        "corp": corp,
        "ticker": ticker,
        "fiscalYear": year,
        "availableFrom": f"{rcept[:4]}-{rcept[4:6]}-{rcept[6:8]}",
        "rceptNo": rcept,
        "fsDiv": fs_div,
        "periodEnd": period_end,
        "currency": str(rows[0].get("currency", "")).strip() or None,
        "sicCode": sic,
        **vals,
        "accountSource": how,
    }
    return rec, None


# ── 수집 ───────────────────────────────────────────────────────
def target_corps():
    """corp → ticker. 조인 키는 corp_code다(계약 4). ticker는 사람이 읽는 보조 필드다.

    A1b가 A0.7 − A1a 차집합이라 겹칠 수 없지만, 겹치면 A1a를 우선한다 —
    ticker 재사용 시 현재 상장분의 ticker가 맞다.
    """
    out = {}
    for r in load_jsonl(A1B):
        out[r["corp"]] = {"ticker": r["ticker"], "group": "delisted"}
    for r in load_jsonl(A1A):
        out[r["corp"]] = {"ticker": r["ticker"], "group": "current"}
    return out


def state_path(shard):
    return f"{SHARD_DIR}/_state-{shard}.json"


def shard_path(shard):
    return f"{SHARD_DIR}/shard-{shard}.jsonl"


def load_state(shard, shards, pol):
    p = state_path(shard)
    if os.path.exists(p):
        st = load_json(p)
        if st.get("shards") == shards and st.get("fundamentalsPolicy") == pol["version"]:
            return st
        # 샤드 수나 정책이 바뀌면 담당 법인 집합과 수집 규칙이 달라진다.
        # 이어받으면 어느 규칙으로 모은 레코드인지 알 수 없으므로 버리고 다시 시작한다.
        print(f"  이전 상태 폐기 — shards {st.get('shards')}→{shards} · "
              f"정책 {st.get('fundamentalsPolicy')}→{pol['version']}")
    return {"stage": "A3", "shard": shard, "shards": shards,
            "fundamentalsPolicy": pol["version"], "corpsDone": [],
            "fsDivHint": {}, "callsUsedToday": 0, "lastRunDate": None,
            # 수집이 며칠에 걸치므로 산출물은 혼합 시점 스냅샷이 된다. PIT는 깨지지 않지만
            # (각 레코드가 자기 availableFrom을 들고 있다) 재현성은 깨진다 — 재수집 시
            # 바이트가 달라졌을 때 그게 버그인지 정정공시인지 가를 근거를 여기 남긴다.
            "runDates": [], "complete": False}


def save_progress(shard, state, records):
    """상태와 산출을 함께 쓴다. 산출은 매번 통째로 다시 쓴다 — append로 이어붙이면
    법인 스캔 도중에 죽었을 때 부분 레코드가 남고, 재개하면 같은 키가 두 벌이 된다."""
    os.makedirs(SHARD_DIR, exist_ok=True)
    with open(shard_path(shard), "w", encoding="utf-8", newline="\n") as f:
        for k in sorted(records):
            f.write(json.dumps(records[k], ensure_ascii=False) + "\n")
    with open(state_path(shard), "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def rec_key(r):
    # 정정공시는 중복이 아니라 사실이다. availableFrom을 키에서 빼면 '그 시점에 알던 값'이 사라진다.
    return (r["corp"], r["fiscalYear"], r["availableFrom"])


def scan_corp(corp, ticker, pol, counters, state):
    """한 법인의 전 사업연도. (레코드 목록, 하드에러 수, 한도초과 여부)"""
    years = range(pol["fiscalYearFrom"], pol["fiscalYearTo"] + 1)
    order = list(pol["source"]["fsDivOrder"])
    hint = state["fsDivHint"].get(corp)
    if hint in order:
        order = [hint] + [d for d in order if d != hint]

    quota_status = pol["quota"]["quotaExceededStatus"]
    out, hard, any_found, empty_run = [], 0, False, 0
    sic = None

    for y in years:
        got, year_hard = None, False
        for div in order:
            rows, st, err = dart_call("fnlttSinglAcntAll.json", {
                "corp_code": corp, "bsns_year": str(y),
                "reprt_code": pol["source"]["reprtCode"], "fs_div": div}, pol, counters)
            time.sleep(pol["requestSleepSeconds"])
            if st == quota_status:
                return out, hard, True
            if err:
                hard += 1
                year_hard = True
                counters["hardErrors"] += 1
                continue
            if rows:
                got = (rows, div)
                state["fsDivHint"][corp] = div
                break
        if got is None:
            # 하드 실패한 해를 '보고서 없음'으로 세지 않는다. 그렇게 하면 일시적인
            # 네트워크 오류 세 번이 조기 종료를 불러 그 법인의 이후 이력을 통째로 자른다.
            if any_found and not year_hard:
                empty_run += 1
                if empty_run >= pol["stopAfterConsecutiveEmptyYears"]:
                    # 보고서를 낸 적 있는 법인이 연속으로 비면 그 뒤는 영원히 빈다.
                    # 폐지 법인 1,222건의 호출을 크게 줄이는 지점이다.
                    counters["earlyStopped"] += 1
                    break
            continue

        empty_run = 0
        if not any_found:
            any_found = True
            # 업종은 보고서가 하나라도 있는 법인에만 묻는다. 전 법인에 묻으면
            # 재무가 아예 없는 법인 몫으로 호출 예산이 새어 나간다.
            # 조회 실패는 레코드를 버리는 사유가 아니다 — sicCode 결측은 하류에서
            # 'general'로 채점되는 정상 경로이고, 여기서 버리면 재무 전체를 잃는다.
            sic = fetch_sic(corp, pol, counters)

        rec, why = build_record(corp, ticker, y, got[0], got[1], sic, pol)
        if rec is None:
            counters["recordRejected"][why] += 1
            continue
        out.append(rec)

    return out, hard, False


def fetch_sic(corp, pol, counters):
    """company.json은 list가 아니라 최상위 필드로 온다 — 전용 경로가 필요하다."""
    for i in range(pol["retryAttempts"]):
        counters["calls"] += 1
        try:
            r = requests.get(f"{BASE}/{pol['source']['companyEndpoint']}",
                             params={"crtfc_key": KEY, "corp_code": corp})
            if 200 <= r.status_code < 300:
                j = r.json()
                st = str(j.get("status", ""))
                counters["dartStatus"][st] += 1
                if st == "000":
                    return (str(j.get("induty_code", "")).strip() or None)
                if st in (DART_NO_DATA, pol["quota"]["quotaExceededStatus"]):
                    return None
        except Exception:  # noqa: BLE001
            pass
        if i < pol["retryAttempts"] - 1:
            time.sleep(pol["retryBackoffBase"] ** i)
    counters["sicFetchFailed"] += 1
    return None


def run_shard(shard, shards, pol, limit):
    diag_path = f"{SHARD_DIR}/_diagnostics-shard-{shard}.json"
    counters = {"calls": 0, "dartStatus": Counter(), "hardErrors": 0,
                "earlyStopped": 0, "sicFetchFailed": 0,
                "recordRejected": Counter()}
    diag = {"stage": "A3", "mode": "shard", "shard": shard, "shards": shards,
            "fundamentalsPolicy": pol["version"], "runDate": today_kst()}
    if limit:
        # 스모크 테스트는 산출물을 만들 수 있지만 verify-diagnostics가 이 플래그를 보고
        # 거부한다. 통과를 만들 수 없는 한 방향 훅이다.
        diag["smokeTest"] = True

    if not KEY:
        _abort("DART_API_KEY 환경변수가 없다", diag, diag_path)

    corps = target_corps()
    ordered = sorted(corps)
    # 라운드로빈 — 연속 구간으로 자르면 폐지 법인이 특정 샤드에 몰려 소요가 크게 갈린다.
    mine = [c for i, c in enumerate(ordered) if i % shards == shard]
    if limit:
        mine = mine[:limit]

    state = load_state(shard, shards, pol)
    if state["lastRunDate"] != diag["runDate"]:
        state["callsUsedToday"] = 0     # DART 한도는 KST 하루 단위다
        state["lastRunDate"] = diag["runDate"]
    state.setdefault("runDates", [])
    if diag["runDate"] not in state["runDates"]:
        state["runDates"].append(diag["runDate"])
    budget = (pol["quota"]["dailyCallLimit"] - pol["quota"]["safetyMarginCalls"]) // shards

    done = set(state["corpsDone"])
    # 이전 실행의 산출을 읽되 '완료된 법인'의 것만 남긴다. 스캔 도중 죽은 법인의
    # 부분 레코드를 그대로 두면 재개분과 겹쳐 같은 키가 두 벌이 된다.
    records = {}
    if os.path.exists(shard_path(shard)):
        for r in load_jsonl(shard_path(shard)):
            if r["corp"] in done:
                records[rec_key(r)] = r

    todo = [c for c in mine if c not in done]
    print(f"A3 샤드 {shard}/{shards} — 담당 {len(mine)}법인 · 완료 {len(mine)-len(todo)} · "
          f"남음 {len(todo)}")
    print(f"  사업연도 {pol['fiscalYearFrom']}~{pol['fiscalYearTo']} · "
          f"오늘 예산 {budget - state['callsUsedToday']}/{budget}건 "
          f"(사용 {state['callsUsedToday']})")

    # 정찰 2회(교훈32) — 경로가 막혔으면 3,801법인을 돌리지 않고 즉시 중단한다.
    probes = []
    for pc in pol["probeCorps"]:
        rows, st, err = dart_call("fnlttSinglAcntAll.json", {
            "corp_code": pc, "bsns_year": str(pol["probeYear"]),
            "reprt_code": pol["source"]["reprtCode"], "fs_div": "CFS"}, pol, counters)
        probes.append({"corp": pc, "ok": bool(rows), "dartStatus": st, "error": err})
        time.sleep(pol["requestSleepSeconds"])
    diag["probes"] = probes
    if not any(p["ok"] for p in probes):
        _abort("정찰 전건 실패 — 수집 경로가 막혔다", diag, diag_path,
               {"lastHttp": LAST_HTTP})
    print(f"  정찰 {sum(1 for p in probes if p['ok'])}/{len(probes)} 통과")

    consec_hard, quota_hit, budget_hit = 0, False, False
    t0 = time.time()
    processed = 0

    for corp in todo:
        if state["callsUsedToday"] + counters["calls"] >= budget:
            budget_hit = True
            break
        recs, hard, quota = scan_corp(corp, corps[corp]["ticker"], pol, counters, state)
        if quota:
            quota_hit = True
            break
        for r in recs:
            records[rec_key(r)] = r
        done.add(corp)
        state["corpsDone"] = sorted(done)
        processed += 1

        consec_hard = consec_hard + 1 if (hard and not recs) else 0
        if consec_hard >= pol["circuitBreakerConsecutiveFailures"]:
            state["callsUsedToday"] += counters["calls"]
            save_progress(shard, state, records)
            diag.update(corpsProcessed=processed, recordCount=len(records),
                        calls=counters["calls"], lastHttp=LAST_HTTP)
            _abort(f"연속 하드 실패 {consec_hard}법인 — 루프 도중 경로가 막혔다",
                   diag, diag_path)

        if processed % 25 == 0:
            state["callsUsedToday"] += counters["calls"]
            counters["calls"] = 0
            save_progress(shard, state, records)
            print(f"  {processed}/{len(todo)} · {len(records)}레코드 · "
                  f"호출 {state['callsUsedToday']} · {time.time()-t0:.0f}s")

    state["callsUsedToday"] += counters["calls"]
    state["complete"] = len(done) >= len(mine)
    save_progress(shard, state, records)

    diag.update(
        corpsAssigned=len(mine), corpsDone=len(done), corpsProcessed=processed,
        recordCount=len(records), calls=state["callsUsedToday"], budget=budget,
        dartStatus=dict(counters["dartStatus"]), hardErrors=counters["hardErrors"],
        earlyStopped=counters["earlyStopped"], sicFetchFailed=counters["sicFetchFailed"],
        recordRejected=dict(counters["recordRejected"]),
        quotaExceeded=quota_hit, budgetExhausted=budget_hit,
        complete=state["complete"], elapsedSeconds=round(time.time() - t0, 1))
    with open(f"{SHARD_DIR}/_diagnostics-shard-{shard}.json", "w",
              encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    tail = ("완료" if state["complete"] else
            "한도 초과 — 다음 실행이 이어받는다" if quota_hit else
            "오늘 예산 소진 — 다음 실행이 이어받는다" if budget_hit else "중단(원인 미상)")
    print(f"\n{shard_path(shard)} — {len(records)}레코드 · "
          f"법인 {len(done)}/{len(mine)} · 호출 {state['callsUsedToday']} · {tail}")
    # 예산 소진은 실패가 아니라 정상적인 분할 실행이다. exit(1)을 내면 매일 빨간 불이 된다.
    return 0


# ── finalize ───────────────────────────────────────────────────
def write_gz(path, records, pol, fields=None):
    o = pol["output"]
    buf = io.BytesIO()
    for x in records:
        row = {k: x.get(k) for k in fields} if fields else x
        buf.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    raw = buf.getvalue()
    with open(path, "wb") as fh:
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=fh,
                           compresslevel=o["gzipCompressLevel"], mtime=o["gzipMtime"])
        gz.write(raw)
        gz.close()
    return len(raw), os.path.getsize(path)


def coverage_of(rec, required):
    return all(rec.get(k) is not None for k in required)


def validate(rows, corps, pol, diag):
    a = pol["acceptance"]
    required = pol["accounts"]["requiredForCoverage"]
    print("\n[인수 조건]")

    inject = os.environ.get("A3_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    # ── 식별자·날짜 계약 ──────────────────────────────────────
    bad_corp = [r for r in rows if not CORP_RE.match(r.get("corp") or "")]
    chk(len(bad_corp) == a["corpContractViolations"],
        f"corp_code 계약 [0-9]{{8}} (위반 {len(bad_corp)}건) — 재무 조인은 이 키로만 한다")
    bad_ticker = [r for r in rows if not TICKER_RE.match(r.get("ticker") or "")]
    diag["tickerContractViolations"] = len(bad_ticker)
    warn(not bad_ticker, f"ticker 계약 [0-9A-Z]{{6}} 위반 {len(bad_ticker)}건 (보조 필드라 WARN)")

    no_af = [r for r in rows if not DATE_RE.match(r.get("availableFrom") or "")]
    chk(len(no_af) == a["availableFromMissing"],
        f"availableFrom 존재·형식 (위반 {len(no_af)}건)")
    no_pe = [r for r in rows if not DATE_RE.match(r.get("periodEnd") or "")]
    chk(len(no_pe) == a["periodEndMissing"], f"periodEnd 존재·형식 (위반 {len(no_pe)}건)")

    # ── PIT 계약 1 — A3의 존재 이유 ────────────────────────────
    bad_pit = [r for r in rows
               if DATE_RE.match(r.get("availableFrom") or "")
               and DATE_RE.match(r.get("periodEnd") or "")
               and not (r["availableFrom"] > r["periodEnd"])]
    diag["availableFromNotAfterPeriodEnd"] = len(bad_pit)
    diag["availableFromNotAfterPeriodEndSample"] = [
        {k: r[k] for k in ("corp", "fiscalYear", "availableFrom", "periodEnd")}
        for r in bad_pit[:20]]
    chk(len(bad_pit) == a["availableFromNotAfterPeriodEnd"],
        f"availableFrom > periodEnd (위반 {len(bad_pit)}건) — "
        f"위반은 로직 반전이거나 periodEnd 파싱 오류다")

    lags = sorted((datetime.strptime(r["availableFrom"], "%Y-%m-%d")
                   - datetime.strptime(r["periodEnd"], "%Y-%m-%d")).days
                  for r in rows
                  if DATE_RE.match(r.get("availableFrom") or "")
                  and DATE_RE.match(r.get("periodEnd") or ""))
    if lags:
        diag["disclosureLagDays"] = {
            "min": lags[0], "p50": lags[len(lags) // 2],
            "p95": lags[min(int(len(lags) * 0.95), len(lags) - 1)], "max": lags[-1]}
        print(f"  ..    공시지연 p50={diag['disclosureLagDays']['p50']}일 "
              f"p95={diag['disclosureLagDays']['p95']}일 "
              f"max={diag['disclosureLagDays']['max']}일 (관측 — 게이트 아님)")

    # ── 유일성 ────────────────────────────────────────────────
    keys = {rec_key(r) for r in rows}
    dup = len(rows) - len(keys)
    chk(dup == a["duplicateKeys"],
        f"(corp, fiscalYear, availableFrom) 중복 {dup}건 — 정정공시는 중복이 아니라 사실이다")

    restated = Counter((r["corp"], r["fiscalYear"]) for r in rows)
    n_restated = sum(1 for v in restated.values() if v > 1)
    diag["restatedFiscalYears"] = n_restated
    print(f"  ..    같은 (corp, fiscalYear)에 availableFrom이 둘 이상인 건 {n_restated}건 "
          f"(정정공시 — 병합하지 않는다)")

    # ── 사업연도 축 ───────────────────────────────────────────
    years = list(range(pol["fiscalYearFrom"], pol["fiscalYearTo"] + 1))
    by_year = defaultdict(list)
    for r in rows:
        by_year[r["fiscalYear"]].append(r)
    out_of_range = [r for r in rows if r["fiscalYear"] not in years]
    diag["fiscalYearOutOfRange"] = len(out_of_range)
    chk(not out_of_range, f"정책 구간 밖 사업연도 {len(out_of_range)}건")

    empty_years = [y for y in years if not by_year.get(y)]
    diag["yearsWithNoData"] = len(empty_years)
    diag["yearsWithNoDataList"] = empty_years
    chk(len(empty_years) == a["yearsWithNoData"],
        f"데이터가 0건인 사업연도 {len(empty_years)}개 {empty_years}")

    # ── 계약 2: 연도별 계정 매칭 성공률 ────────────────────────
    year_cov = {}
    for y in years:
        xs = by_year.get(y, [])
        full = sum(1 for r in xs if coverage_of(r, required))
        year_cov[str(y)] = {"records": len(xs), "full": full,
                            "rate": round(full / len(xs), 4) if xs else None}
    diag["yearCoverage"] = year_cov

    per_account_year = {}
    for y in years:
        xs = by_year.get(y, [])
        if not xs:
            continue
        per_account_year[str(y)] = {
            k: round(sum(1 for r in xs if r.get(k) is not None) / len(xs), 4)
            for k in pol["accounts"]["spec"]}
    diag["accountCoverageByYear"] = per_account_year

    rates = [v["rate"] for v in year_cov.values() if v["rate"] is not None]
    med = median(rates) if rates else 0
    dropped = [y for y, v in year_cov.items()
               if v["rate"] is not None and med - v["rate"] > a["yearCoverageDropWarn"]]
    diag["yearCoverageMedian"] = round(med, 4)
    diag["yearCoverageDropped"] = dropped
    # 계약 2. FN-1.0에서는 WARN이다 — 실측 기준선이 아직 없다.
    # 전체 평균이 아니라 중앙값 대비 낙폭을 보는 이유: 평균만 보면 한 해가 무너져도
    # 나머지 열 해가 가린다.
    warn(not dropped,
         f"연도별 매칭률이 중앙값({med:.1%}) 대비 "
         f"{a['yearCoverageDropWarn']*100:.0f}%p 이상 낮은 사업연도 {dropped}")

    # ── 커버리지 ──────────────────────────────────────────────
    full_cnt = sum(1 for r in rows if coverage_of(r, required))
    cov_rate = full_cnt / len(rows) if rows else 0
    diag["coverageRate"] = round(cov_rate, 5)
    diag["coverageRequiredAccounts"] = required
    warn(cov_rate >= a["coverageRateMinWarn"],
         f"필수 {len(required)}계정 전부 확보 {cov_rate*100:.1f}% >= "
         f"{a['coverageRateMinWarn']*100:.0f}% ({full_cnt}/{len(rows)})")

    corps_with = {r["corp"] for r in rows}
    diag["corpsWithData"] = len(corps_with)
    diag["corpsTargeted"] = len(corps)
    diag["corpsWithoutData"] = len(corps) - len(corps_with)
    by_group = Counter(corps[c]["group"] for c in corps_with if c in corps)
    tgt_group = Counter(v["group"] for v in corps.values())
    diag["corpsWithDataByGroup"] = dict(by_group)
    diag["corpsTargetedByGroup"] = dict(tgt_group)
    # 폐지 법인의 확보율을 따로 남긴다. 전체 비율만 보면 현재 상장분 2,579가
    # 폐지분 1,222의 공백을 가린다 — A2b 정찰에서 배운 것과 같은 분모 문제다.
    diag["corpsWithDataRateByGroup"] = {
        g: round(by_group.get(g, 0) / tgt_group[g], 4) for g in tgt_group}
    warn(len(corps_with) >= a["minCorpsWithDataWarn"],
         f"재무 확보 법인 {len(corps_with)} >= {a['minCorpsWithDataWarn']} "
         f"(대상 {len(corps)} · 그룹별 {diag['corpsWithDataRateByGroup']})")

    # ── 계약 3: |ROE| > 200% ──────────────────────────────────
    thr = a["roeAbsOutlierThreshold"]
    roes = [(r, r["netIncome"] / r["equity"])
            for r in rows
            if r.get("netIncome") is not None and r.get("equity")]
    outliers = [(r, v) for r, v in roes if abs(v) > thr]
    neg_eq = [r for r in rows if r.get("equity") is not None and r["equity"] < 0]
    diag["roeComputable"] = len(roes)
    diag["roeAbsOutlierCount"] = len(outliers)
    diag["roeAbsOutlierRate"] = round(len(outliers) / len(roes), 5) if roes else None
    diag["roeAbsOutlierSample"] = [
        {"corp": r["corp"], "ticker": r["ticker"], "fiscalYear": r["fiscalYear"],
         "roe": round(v, 3), "equity": r["equity"], "netIncome": r["netIncome"]}
        for r, v in sorted(outliers, key=lambda x: -abs(x[1]))[:30]]
    diag["negativeEquityCount"] = len(neg_eq)
    diag["negativeEquityRate"] = round(len(neg_eq) / len(rows), 5) if rows else None
    # 이상치를 제거하지 않는다. 자본잠식 기업의 ROE는 오류가 아니라 사실이고,
    # 여기서 도려내면 A5가 '정상 기업만 있는 세계'를 채점하게 된다 — 생존편향의 축소판이다.
    warn(diag["roeAbsOutlierRate"] is None
         or diag["roeAbsOutlierRate"] <= a["roeAbsOutlierRateWarn"],
         f"|ROE| > {thr*100:.0f}% {len(outliers)}건 "
         f"({(diag['roeAbsOutlierRate'] or 0)*100:.2f}%) — 제거하지 않고 보고만 한다")
    warn(diag["negativeEquityRate"] is None
         or diag["negativeEquityRate"] <= a["negativeEquityRateWarn"],
         f"자본총계 음수 {len(neg_eq)}건 ({(diag['negativeEquityRate'] or 0)*100:.2f}%)")

    diag["fsDivDistribution"] = dict(Counter(r.get("fsDiv") for r in rows))
    src = Counter()
    for r in rows:
        for k, v in (r.get("accountSource") or {}).items():
            src[f"{k}:{v or 'MISS'}"] += 1
    diag["accountSourceDistribution"] = dict(src)
    diag["sicCodeMissing"] = sum(1 for r in rows if not r.get("sicCode"))

    return rows


def run_finalize(pol):
    diag_path = f"{OUT_DIR}/_diagnostics.json"
    diag = {"stage": "A3", "mode": "finalize", "fundamentalsPolicy": pol["version"],
            "stageVersion": STAGE_VERSION,
            # sicCode는 '현재의 업종'이라 전 사업연도에 같은 값이 붙는다.
            # 이 플래그가 사라지면 하류가 미확정값을 확정값으로 읽는다.
            "sectorNotPointInTime": True}

    shard_files = sorted(glob.glob(f"{SHARD_DIR}/shard-*.jsonl"))
    if not shard_files:
        _abort(f"{SHARD_DIR}에 샤드 산출물이 없다 — 수집 잡을 먼저 돌려라", diag, diag_path)

    # 전 샤드가 담당분을 끝냈는지 확인한다. 예산 소진으로 중단된 샤드가 섞이면
    # 부분 수집물에 manifest가 찍힌다 — manifest는 '인수 조건을 통과했다'는 뜻이다(교훈43).
    incomplete, run_dates = [], set()
    for p in sorted(glob.glob(f"{SHARD_DIR}/_state-*.json")):
        st = load_json(p)
        run_dates.update(st.get("runDates") or [])
        if not st.get("complete"):
            incomplete.append({"shard": st.get("shard"),
                               "done": len(st.get("corpsDone", []))})
    diag["shardStatesIncomplete"] = incomplete
    # 수집 창. 하루를 넘으면 산출물은 혼합 시점 스냅샷이며, 그 사실이 여기 남는다 —
    # 재수집으로 해시가 바뀌었을 때 정정공시라는 후보 원인을 가리키는 유일한 근거다.
    rd = sorted(run_dates)
    diag["collectionWindow"] = {"from": rd[0] if rd else None,
                                "to": rd[-1] if rd else None,
                                "runDays": len(rd)}
    if incomplete:
        _abort(f"아직 담당분을 마치지 않은 샤드 {len(incomplete)}개 {incomplete} — "
               f"수집을 이어서 돌려라", diag, diag_path)

    rows = []
    for p in shard_files:
        rows.extend(load_jsonl(p))
    diag["shardFiles"] = [os.path.basename(p) for p in shard_files]
    diag["shardCount"] = len(shard_files)
    diag["rowCount"] = len(rows)
    print(f"[1/3] 샤드 {len(shard_files)}개 병합 — {len(rows)}레코드")

    if not rows:
        _abort("병합 결과 0레코드", diag, diag_path)

    for p in shard_files:
        d = f"{SHARD_DIR}/_diagnostics-{os.path.basename(p).replace('.jsonl','')}.json"
        if os.path.exists(d) and load_json(d).get("smokeTest"):
            diag["smokeTest"] = True

    corps = target_corps()
    diag["fiscalYearFrom"] = pol["fiscalYearFrom"]
    diag["fiscalYearTo"] = pol["fiscalYearTo"]
    now = datetime.now(KST)
    expected_to = now.year - 1 if now.month >= 4 else now.year - 2
    diag["fiscalYearToExpectedByRule"] = expected_to
    cw = diag["collectionWindow"]
    print(f"[2/3] 사업연도 {pol['fiscalYearFrom']}~{pol['fiscalYearTo']} · "
          f"대상 법인 {len(corps)} · 수집 창 {cw['from']}~{cw['to']} ({cw['runDays']}일)")
    if cw["runDays"] > 1:
        print("  ..    수집이 하루를 넘었다 — 혼합 시점 스냅샷이다. PIT는 유지되지만"
              " 재수집 시 정정공시로 바이트가 달라질 수 있다")

    rows = validate(rows, corps, pol, diag)
    # 규칙 대조는 인수 조건 뒤에 둔다. 값을 박은 이유(재현성)와 낡음을 알리는 수단(WARN)이
    # 다른 층이라, 이것이 FAIL이면 해가 바뀔 때마다 파이프라인이 멈춘다.
    warn(pol["fiscalYearTo"] >= expected_to,
         f"fiscalYearTo {pol['fiscalYearTo']} >= 규칙상 최신 사업연도 {expected_to} "
         f"(WARN이면 정책 값을 올릴 때가 됐다는 뜻이다)")

    os.makedirs(OUT_DIR, exist_ok=True)
    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    if warns:
        print(f"\nWARN {len(warns)}건 (실패 아님, 확인 필요):")
        for w in warns:
            print(f"  - {w}")

    # 인수 조건 실패 시 산출물을 쓰지 않는다(교훈43).
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 산출물을 쓰지 않는다")
        for x in fails:
            print(f"  - {x}")
        return 1

    print("\n[3/3] 사업연도 분할 · gzip")
    fields = pol["output"]["fields"]
    rows.sort(key=lambda r: (r["fiscalYear"], r["corp"], r["availableFrom"]))
    by_year = defaultdict(list)
    for r in rows:
        by_year[r["fiscalYear"]].append(r)

    # 이전 실행의 잔재를 남기지 않는다 — 대상이 줄면 빈 연도 파일이 남아
    # 디렉터리 해시가 사실과 달라진다.
    for old in glob.glob(f"{OUT_DIR}/*.jsonl.gz"):
        os.remove(old)

    years = {}
    for y in sorted(by_year):
        raw, gz = write_gz(f"{OUT_DIR}/{y}.jsonl.gz", by_year[y], pol, fields)
        years[str(y)] = {"records": len(by_year[y]), "rawBytes": raw, "gzBytes": gz}
        print(f"  {y}.jsonl.gz  {len(by_year[y]):>6}레코드  "
              f"{raw/1e6:6.2f}MB → {gz/1e6:5.2f}MB")
    diag["years"] = years
    diag["totalGzBytes"] = sum(v["gzBytes"] for v in years.values())

    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{OUT_DIR} — 사업연도 {len(years)}개 · {len(rows)}레코드 · "
          f"{diag['totalGzBytes']/1e6:.1f}MB")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int)
    ap.add_argument("--shards", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="스모크 테스트용. 진단에 smokeTest 플래그가 박히고 CI가 거부한다")
    args = ap.parse_args()

    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음 — FN-1.0 정책 파일이 필요하다")
        return 1
    pol = load_json(POLICY)
    for p in (A1A, A1B):
        if not os.path.exists(p):
            print(f"{p} 없음 — 상류 단계(A1a·A1b)를 먼저 실행하라")
            return 1

    if args.finalize:
        return run_finalize(pol)
    if args.shard is None:
        print("--shard N --shards M 또는 --finalize 중 하나가 필요하다")
        return 1
    shards = args.shards or pol["shards"]
    if not (0 <= args.shard < shards):
        print(f"--shard는 0 이상 {shards} 미만이어야 한다")
        return 1
    return run_shard(args.shard, shards, pol, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
