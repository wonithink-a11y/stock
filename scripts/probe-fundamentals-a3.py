#!/usr/bin/env python3
"""A3 재무(PIT) 정찰 — 수집이 아니라 설계 판정이다.

A3는 미지수 세 개가 설계를 좌우한다. 어느 것도 문서로 확정할 수 없어서 실측한다.

  1. availableFrom을 얻을 경로가 있는가
     PIT의 정의가 여기 걸린다. 응답의 rcept_no 앞 8자리가 접수일이면 추가 호출 없이
     availableFrom을 얻는다. 없으면 list.json을 corp×연도로 한 번 더 돌아야 하고
     호출량이 두 배가 된다 — 일 한도 20,000건 설계가 통째로 바뀐다.
  2. 어느 엔드포인트로 계정을 잡는가
     fnlttSinglAcnt(주요계정)는 호출 1회로 3개 연도를 주지만 account_nm(회사·연도마다
     다른 한글 이름)으로만 매칭된다. fnlttSinglAcntAll(전체 재무제표)은 account_id
     (IFRS 표준 태그)를 주지만 fs_div가 필수라 호출이 최대 2배다.
     계약 7("계정과목명이 회사·연도마다 다르다")이 실제로 얼마나 아픈지가 이 선택을 정한다.
  3. 폐지 종목을 받을 수 있는가
     A1b 1,222건은 DART에 법인 레코드가 남아 있지만 재무제표까지 남아 있는지는 다르다.
     A2b 정찰에서 배운 것 — 게이트의 분모를 먼저 정하지 않으면 커버리지가 통과율로 위장한다.

정찰은 어떤 결과든 exit 0으로 끝낸다. 산출물은 데이터가 아니라 패턴이다(교훈39).
재무 수치는 남기지 않는다 — 표본 몇 건의 계정 매칭 여부만 남긴다.

입력: DART_API_KEY (환경변수) · A1a·A1b 산출물
출력: data/backfill/_probe-fundamentals-a3.json
"""
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
OUT = "data/backfill/_probe-fundamentals-a3.json"
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")
KST = timezone(timedelta(hours=9))

REPRT_ANNUAL = "11011"          # 사업보고서(연간)
YEARS = list(range(2014, 2026))  # 2014를 넣는 이유는 '2015부터'라는 주장을 실측하기 위해서다
SLEEP = 0.2

# 표본. 무작위가 아니라 고정 앵커 + 균등 간격이다 — 정찰을 다시 돌려도 같은 표본이어야
# 두 실행의 차이가 표본 차이가 아니라 소스 변화라고 말할 수 있다.
# 앵커는 업종 양식이 갈리는 지점을 일부러 고른다: 금융(재무제표 형태 자체가 다르다)·
# 지주·바이오·건설·해운·항공·유틸리티·통신.
ANCHOR_TICKERS = ["005930", "105560", "003550", "068270",
                  "006360", "011200", "003490", "015760", "017670"]
SAMPLE_CURRENT = 24
SAMPLE_DELISTED = 8

# 필요한 계정 7개. idTails는 IFRS 태그의 접두사를 뗀 꼬리다 —
# 2019년 전후로 'ifrs_Equity' → 'ifrs-full_Equity'로 접두사가 바뀌었으므로
# 접두사째 비교하면 옛 연도가 통째로 미매칭으로 잡힌다.
ACCOUNTS = {
    "currentAssets": {"sj": ["BS"], "idTails": ["CurrentAssets"],
                      "exact": ["유동자산"], "contains": []},
    "currentLiab":   {"sj": ["BS"], "idTails": ["CurrentLiabilities"],
                      "exact": ["유동부채"], "contains": []},
    "liabilities":   {"sj": ["BS"], "idTails": ["Liabilities"],
                      "exact": ["부채총계"], "contains": []},
    "equity":        {"sj": ["BS"], "idTails": ["Equity"],
                      "exact": ["자본총계"], "contains": []},
    "revenue":       {"sj": ["IS", "CIS"], "idTails": ["Revenue"],
                      "exact": ["매출액", "수익(매출액)", "영업수익"],
                      "contains": ["영업수익", "매출"]},
    "opProfit":      {"sj": ["IS", "CIS"], "idTails": ["OperatingIncomeLoss"],
                      "exact": ["영업이익"], "contains": ["영업이익"]},
    "netIncome":     {"sj": ["IS", "CIS"], "idTails": ["ProfitLoss"],
                      "exact": ["당기순이익"], "contains": ["당기순이익"]},
}

DATE8 = re.compile(r"^\d{8}$")
# thstrm_dt는 "2023.01.01 ~ 2023.12.31" 또는 "2023.12.31 현재" 두 형태로 온다.
# 회계기간말은 어느 쪽이든 마지막 날짜다.
DT_IN_TEXT = re.compile(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})")

LAST_HTTP = {"endpoint": None, "status": None, "dartStatus": None, "bytes": None}

_orig_send = requests.adapters.HTTPAdapter.send


def _send(self, request, **kw):
    if kw.get("timeout") is None:
        kw["timeout"] = (10, 60)
    return _orig_send(self, request, **kw)


requests.adapters.HTTPAdapter.send = _send


def dart_get(endpoint, params):
    """(json, dartStatus, error) — 키는 절대 로그·산출물에 넣지 않는다.

    DART는 조회 실패도 HTTP 200 + status 필드로 돌려준다(교훈38의 재판). 그래서
    HTTP status만 보면 '데이터 없음'과 '정상'이 구분되지 않는다. 두 축을 다 남긴다.
    """
    url = f"{BASE}/{endpoint}"
    q = {"crtfc_key": KEY, **params}
    try:
        r = requests.get(url, params=q)
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


def id_tail(account_id):
    """'ifrs-full_Equity' · 'ifrs_Equity' → 'Equity'."""
    s = (account_id or "").strip()
    if not s or s.startswith("-"):   # '-표준계정코드 미사용-'
        return None
    return s.split("_", 1)[1] if "_" in s else s


def match_accounts(rows, use_id):
    """계정 7개를 몇 개나 잡았는지만 돌려준다. 금액은 보지 않는다 — 정찰의 산출물은
    수치가 아니라 '이 방식으로 잡히는가'이기 때문이다."""
    hit = {}
    for key, spec in ACCOUNTS.items():
        cand = [r for r in rows if str(r.get("sj_div", "")) in spec["sj"]] or rows
        found = None
        if use_id:
            tails = set(spec["idTails"])
            for r in cand:
                if id_tail(r.get("account_id")) in tails:
                    found = "id"
                    break
        if not found:
            for r in cand:
                nm = str(r.get("account_nm", "")).replace(" ", "")
                if nm in spec["exact"]:
                    found = "nameExact"
                    break
        if not found:
            for r in cand:
                nm = str(r.get("account_nm", "")).replace(" ", "")
                if any(c in nm for c in spec["contains"]):
                    found = "nameContains"
                    break
        hit[key] = found
    return hit


def parse_period_end(rows):
    """보고서가 스스로 말하는 회계기간말. A1a의 fiscalMonth보다 이쪽이 우선이다 —
    fiscalMonth는 '현재의 결산월'이라 결산월을 변경한 회사의 과거 보고서와 어긋난다."""
    for r in rows:
        for field in ("thstrm_dt", "thstrm_nm"):
            hits = DT_IN_TEXT.findall(str(r.get(field, "")))
            if hits:
                y, m, d = hits[-1]
                return f"{y}-{m}-{d}"
    return None


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def pick_sample():
    cur = load_jsonl(A1A)
    dl = load_jsonl(A1B)
    by_ticker = {c["ticker"]: c for c in cur}

    picked, seen = [], set()
    for tk in ANCHOR_TICKERS:
        c = by_ticker.get(tk)
        if c and c["corp"] not in seen:
            picked.append({**c, "group": "current", "anchor": True})
            seen.add(c["corp"])

    rest = sorted((c for c in cur if c["corp"] not in seen), key=lambda c: c["ticker"])
    need = max(SAMPLE_CURRENT - len(picked), 0)
    if need and rest:
        step = max(len(rest) // need, 1)
        for c in rest[::step][:need]:
            picked.append({**c, "group": "current", "anchor": False})
            seen.add(c["corp"])

    dl_sorted = sorted(dl, key=lambda c: c["corp"])
    if dl_sorted and SAMPLE_DELISTED:
        step = max(len(dl_sorted) // SAMPLE_DELISTED, 1)
        for c in dl_sorted[::step][:SAMPLE_DELISTED]:
            if c["corp"] in seen:
                continue
            picked.append({"ticker": c["ticker"], "name": c.get("corpName"),
                           "corp": c["corp"], "market": None,
                           "fiscalMonth": None, "group": "delisted", "anchor": False})
            seen.add(c["corp"])
    return picked


# ── 관측 축 ────────────────────────────────────────────────────
def new_stats():
    return {
        "calls": 0,
        "dartStatus": Counter(),
        "reportsFound": 0,
        "rceptNoPresent": 0,
        "rceptNoIsDate": 0,
        "periodEndParsed": 0,
        "availableFromAfterPeriodEnd": 0,
        "availableFromNotAfterPeriodEnd": 0,
        "lagDays": [],
        "accountHits": defaultdict(Counter),   # 계정 → 매칭수단 → 건수
        "fullHitReports": 0,                   # 7개 전부 잡힌 보고서 수
        "byYear": defaultdict(lambda: {"calls": 0, "reports": 0, "fullHit": 0}),
        "fsDiv": Counter(),
    }


def days_between(a, b):
    return (datetime.strptime(a, "%Y-%m-%d") - datetime.strptime(b, "%Y-%m-%d")).days


def record(stats, year, rows, use_id, fs_div, samples, meta):
    stats["reportsFound"] += 1
    stats["byYear"][year]["reports"] += 1
    if fs_div:
        stats["fsDiv"][fs_div] += 1

    rcept = str(rows[0].get("rcept_no", "")).strip()
    available_from = None
    if rcept:
        stats["rceptNoPresent"] += 1
        if DATE8.match(rcept[:8]):
            stats["rceptNoIsDate"] += 1
            available_from = f"{rcept[:4]}-{rcept[4:6]}-{rcept[6:8]}"

    period_end = parse_period_end(rows)
    if period_end:
        stats["periodEndParsed"] += 1

    if available_from and period_end:
        # 계약 1. 음수면 로직 반전이므로 여기서 방향까지 세어 둔다.
        if available_from > period_end:
            stats["availableFromAfterPeriodEnd"] += 1
        else:
            stats["availableFromNotAfterPeriodEnd"] += 1
        try:
            stats["lagDays"].append(days_between(available_from, period_end))
        except ValueError:
            pass

    hits = match_accounts(rows, use_id)
    for key, how in hits.items():
        stats["accountHits"][key][how or "MISS"] += 1
    if all(hits.values()):
        stats["fullHitReports"] += 1
        stats["byYear"][year]["fullHit"] += 1

    if len(samples) < 12:
        samples.append({
            **meta, "year": year, "fsDiv": fs_div,
            "rows": len(rows), "availableFrom": available_from,
            "periodEnd": period_end,
            "lagDays": (days_between(available_from, period_end)
                        if available_from and period_end else None),
            "accountHits": hits,
        })


def probe_acnt(corp, year, stats, samples, meta):
    """fnlttSinglAcnt — 주요계정. 호출 1회로 당기·전기·전전기."""
    stats["calls"] += 1
    stats["byYear"][year]["calls"] += 1
    j, st, _err = dart_get("fnlttSinglAcnt.json", {
        "corp_code": corp, "bsns_year": str(year), "reprt_code": REPRT_ANNUAL})
    stats["dartStatus"][st] += 1
    if st != "000":
        return
    rows = j.get("list") or []
    if not rows:
        stats["dartStatus"]["000_EMPTY_LIST"] += 1
        return
    cfs = [r for r in rows if r.get("fs_div") == "CFS"]
    use, div = (cfs, "CFS") if cfs else (rows, "OFS")
    record(stats, year, use, False, div, samples, meta)


def probe_acnt_all(corp, year, stats, samples, meta):
    """fnlttSinglAcntAll — 전체 재무제표. fs_div 필수라 CFS 실패 시 OFS로 한 번 더."""
    for div in ("CFS", "OFS"):
        stats["calls"] += 1
        stats["byYear"][year]["calls"] += 1
        j, st, _err = dart_get("fnlttSinglAcntAll.json", {
            "corp_code": corp, "bsns_year": str(year),
            "reprt_code": REPRT_ANNUAL, "fs_div": div})
        stats["dartStatus"][st] += 1
        if st != "000":
            continue
        rows = j.get("list") or []
        if not rows:
            stats["dartStatus"]["000_EMPTY_LIST"] += 1
            continue
        record(stats, year, rows, True, div, samples, meta)
        return


def summarize(stats):
    lag = sorted(stats["lagDays"])
    def pct(p):
        return lag[min(int(len(lag) * p), len(lag) - 1)] if lag else None
    return {
        "calls": stats["calls"],
        "dartStatus": dict(stats["dartStatus"]),
        "reportsFound": stats["reportsFound"],
        "rceptNoPresent": stats["rceptNoPresent"],
        "rceptNoIsDate": stats["rceptNoIsDate"],
        "periodEndParsed": stats["periodEndParsed"],
        "availableFromAfterPeriodEnd": stats["availableFromAfterPeriodEnd"],
        "availableFromNotAfterPeriodEnd": stats["availableFromNotAfterPeriodEnd"],
        "lagDaysMin": lag[0] if lag else None,
        "lagDaysP50": pct(0.5),
        "lagDaysP95": pct(0.95),
        "lagDaysMax": lag[-1] if lag else None,
        "fullHitReports": stats["fullHitReports"],
        "fullHitRate": (round(stats["fullHitReports"] / stats["reportsFound"], 4)
                        if stats["reportsFound"] else None),
        "accountHits": {k: dict(v) for k, v in stats["accountHits"].items()},
        "accountMissRate": {
            k: round(v.get("MISS", 0) / max(stats["reportsFound"], 1), 4)
            for k, v in stats["accountHits"].items()},
        "fsDiv": dict(stats["fsDiv"]),
        "byYear": {str(y): dict(v) for y, v in sorted(stats["byYear"].items())},
    }


def main() -> int:
    if not KEY:
        print("DART_API_KEY 환경변수가 없다 — 정찰은 네트워크가 필요하다")
        return 1
    for p in (A1A, A1B):
        if not os.path.exists(p):
            print(f"{p} 없음 — 상류 단계를 먼저 실행하라")
            return 1

    sample = pick_sample()
    n_cur = sum(1 for s in sample if s["group"] == "current")
    n_dl = sum(1 for s in sample if s["group"] == "delisted")
    print(f"A3 재무 정찰 — 표본 {len(sample)}개 법인 "
          f"(현재상장 {n_cur} · 폐지 {n_dl}) × 연도 {YEARS[0]}~{YEARS[-1]}")
    print("  (수집 아님. 재무 수치는 남기지 않고 매칭 가능 여부만 잰다)\n")

    acnt, acnt_all = new_stats(), new_stats()
    s_acnt, s_all = [], []
    per_corp = []
    t0 = time.time()

    for i, c in enumerate(sample, 1):
        meta = {"ticker": c["ticker"], "corp": c["corp"], "group": c["group"]}
        before = (acnt["reportsFound"], acnt_all["reportsFound"])
        for y in YEARS:
            probe_acnt(c["corp"], y, acnt, s_acnt, meta)
            time.sleep(SLEEP)
            probe_acnt_all(c["corp"], y, acnt_all, s_all, meta)
            time.sleep(SLEEP)
        per_corp.append({
            **meta, "name": c.get("name"),
            "acntReports": acnt["reportsFound"] - before[0],
            "acntAllReports": acnt_all["reportsFound"] - before[1],
        })
        print(f"  {i}/{len(sample)} {c['ticker']} {c.get('name')} "
              f"[{c['group']}] — 주요계정 {per_corp[-1]['acntReports']}개 / "
              f"전체재무제표 {per_corp[-1]['acntAllReports']}개 보고서 "
              f"({time.time()-t0:.0f}s)")

    # 폐지 종목 커버리지 — A2b 정찰의 교훈이다. 분모를 먼저 정하지 않으면
    # 커버리지가 통과율로 위장한다.
    def cov(group, key):
        xs = [p for p in per_corp if p["group"] == group]
        got = [p for p in xs if p[key] > 0]
        return {"sampled": len(xs), "withAnyReport": len(got),
                "rate": round(len(got) / len(xs), 4) if xs else None,
                "zeroReport": [p["ticker"] for p in xs if p[key] == 0][:20]}

    total_calls = acnt["calls"] + acnt_all["calls"]
    corps_all = 2579 + 1222
    # 호출량 추정 — resume 로직이 필요한지 아닌지를 정하는 유일한 근거다.
    est = {
        "corpsTotal": corps_all,
        "yearsPlanned": len(YEARS),
        "acntCallsPerCorpYear": 1,
        "acntAllCallsPerCorpYear": round(
            acnt_all["calls"] / max(len(sample) * len(YEARS), 1), 2),
        "estimatedCallsAcnt": corps_all * len(YEARS),
        "estimatedCallsAcntAll": int(corps_all * len(YEARS)
                                     * acnt_all["calls"]
                                     / max(len(sample) * len(YEARS), 1)),
        "dartDailyLimit": 20000,
    }
    est["acntFitsInOneDay"] = est["estimatedCallsAcnt"] <= est["dartDailyLimit"]
    est["acntAllFitsInOneDay"] = est["estimatedCallsAcntAll"] <= est["dartDailyLimit"]

    out = {
        "probedAt": datetime.now(KST).isoformat(),
        "stage": "A3-probe",
        "purpose": "설계 판정. 재무 수치를 남기지 않으며 A3 산출물이 아니다",
        "sampleNote": "무작위가 아니라 고정 앵커 + 균등 간격이다. 재실행 시 같은 표본이어야 "
                      "두 실행의 차이를 표본 차이가 아니라 소스 변화로 읽을 수 있다.",
        "sample": {"corps": len(sample), "current": n_cur, "delisted": n_dl,
                   "years": [YEARS[0], YEARS[-1]],
                   "anchors": ANCHOR_TICKERS},

        "endpoints": {
            "fnlttSinglAcnt": summarize(acnt),
            "fnlttSinglAcntAll": summarize(acnt_all),
        },
        "endpointNote": "fnlttSinglAcnt는 호출 1회로 3개 연도(당기·전기·전전기)를 주지만 "
                        "account_nm으로만 매칭된다. fnlttSinglAcntAll은 account_id(IFRS 태그)를 "
                        "주지만 fs_div가 필수라 호출이 최대 2배다. 선택 기준은 accountMissRate와 "
                        "estimatedCalls 둘 다이며, 이 정찰이 그 두 값을 처음으로 실측한다.",

        "pointInTime": {
            "availableFromSource": "rcept_no 앞 8자리",
            "contract": "availableFrom > 회계기간말 (BF-1.1 §7 A3 계약 1)",
            "note": "위반이 0이 아니면 로직 반전이거나 회계기간말 파싱이 틀린 것이다. "
                    "정찰은 어느 쪽인지 단정하지 않고 두 카운터를 따로 남긴다.",
            "amendmentCaveat": "DART가 돌려주는 rcept_no는 정정공시가 있으면 정정본의 것이다. "
                               "따라서 availableFrom은 원본 접수일보다 늦을 수 있다. 방향은 "
                               "보수적이다(더 늦게 알았다고 기록) — look-ahead가 아니라 커버리지 "
                               "손실로 나타난다. lagDaysP95·lagDaysMax가 그 규모를 가리킨다.",
        },

        "coverage": {
            "currentByAcnt": cov("current", "acntReports"),
            "currentByAcntAll": cov("current", "acntAllReports"),
            "delistedByAcnt": cov("delisted", "acntReports"),
            "delistedByAcntAll": cov("delisted", "acntAllReports"),
            "note": "폐지 종목은 DART에 법인 레코드가 남아도 재무제표까지 남는다는 보장이 없다. "
                    "표본 기준이며 전수가 아니다 — A3 게이트의 분모는 이 값이 아니라 "
                    "본 수집의 실측으로 정한다.",
        },

        "callBudget": est,
        "callBudgetNote": "일 한도 20,000건. 초과하면 다음날까지 대기이므로 resume이 "
                          "선택이 아니라 계약이다(BF-1.1 §7 A3 계약 5).",

        "samples": {"fnlttSinglAcnt": s_acnt, "fnlttSinglAcntAll": s_all},
        "perCorp": per_corp,
        "totalCalls": total_calls,
        "elapsedSeconds": round(time.time() - t0, 1),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    a, b = out["endpoints"]["fnlttSinglAcnt"], out["endpoints"]["fnlttSinglAcntAll"]
    print(f"\n{'='*66}")
    print(f"{'':22}{'주요계정':>14}{'전체재무제표':>16}")
    print(f"{'호출':22}{a['calls']:>14}{b['calls']:>16}")
    print(f"{'보고서 확보':20}{a['reportsFound']:>14}{b['reportsFound']:>16}")
    print(f"{'rcept_no=날짜':19}{a['rceptNoIsDate']:>14}{b['rceptNoIsDate']:>16}")
    print(f"{'계약1 만족':21}{a['availableFromAfterPeriodEnd']:>14}"
          f"{b['availableFromAfterPeriodEnd']:>16}")
    print(f"{'계약1 위반':21}{a['availableFromNotAfterPeriodEnd']:>14}"
          f"{b['availableFromNotAfterPeriodEnd']:>16}")
    print(f"{'7계정 전부 매칭':18}{a['fullHitRate']!s:>14}{b['fullHitRate']!s:>16}")
    print(f"{'='*66}")
    print(f"\n계정별 미매칭률")
    for k in ACCOUNTS:
        print(f"  {k:<16} 주요계정 {a['accountMissRate'][k]*100:>6.1f}%   "
              f"전체재무제표 {b['accountMissRate'][k]*100:>6.1f}%")
    print(f"\n공시지연 lag(일)  주요계정 p50={a['lagDaysP50']} p95={a['lagDaysP95']} "
          f"max={a['lagDaysMax']}")
    print(f"폐지 종목 커버리지  주요계정 {out['coverage']['delistedByAcnt']['rate']} · "
          f"전체재무제표 {out['coverage']['delistedByAcntAll']['rate']}")
    print(f"\n호출량 추정 (법인 {est['corpsTotal']} × 연도 {est['yearsPlanned']})")
    print(f"  주요계정      {est['estimatedCallsAcnt']:>8}건  "
          f"일한도 내 {est['acntFitsInOneDay']}")
    print(f"  전체재무제표  {est['estimatedCallsAcntAll']:>8}건  "
          f"일한도 내 {est['acntAllFitsInOneDay']}")
    print(f"\n{OUT} ({out['elapsedSeconds']}s)")
    return 0


if __name__ == "__main__":
    # 정찰의 '발견'은 어떤 결과든 exit 0이다 — 커버리지가 0%라도 그것이 산출물이다.
    # 다만 '정찰이 돌지도 못한 것'(키 없음·상류 산출물 없음)은 발견이 아니라 설정 오류이므로
    # exit 1로 가른다. 둘을 같은 코드로 끝내면 아무것도 재지 않은 실행이 통과로 보인다.
    try:
        rc = main()
    except KeyboardInterrupt:
        print("중단됨")
        rc = 0
    sys.exit(rc)
