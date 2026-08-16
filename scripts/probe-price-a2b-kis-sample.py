"""probe-price-a2b-kis-sample.py — A2b KIS 전량 적용 전 1단계 정찰 (표본)

배경: A2b 대체경로 ④(KIS FHKST03010100)는 단일종목(005930/000660) 프로브로
분할 연속성·페이지네이션 동작을 확인했지만, 1,223건 전체로 확장했을 때의
실제 호출량은 "632건(데이터 있는 종목)의 평균 상장기간을 모른다"는 이유로
5,600~20,800콜로 범위만 추정했다(세션인수인계-2026-08-16.md §4). 이 스크립트는
그 미지수를 표본으로 좁힌다.

이 스크립트는 A2b 코드·정책(price.v1.json, build-price-a2b.py)을 읽지도
바꾸지도 않는다 — 정찰 전용이다.

표본: A1b delisted.jsonl(corp_code 오름차순, 1,223건 전수)에서
random.Random(SEED).sample()로 비복원 무작위 SAMPLE_SIZE건을 뽑고, 재현
가능하도록 seed·인덱스·티커를 결과에 그대로 남긴다.

동시성: CONCURRENCY(기본 2) — CLAUDE.md 수집 VM 운영기준의 시작값을 그대로
가져왔다. 그 기준은 분봉 엔드포인트(FHKST03010230)에서 EGW00201 실측으로 얻은
값이라, 이 스크립트가 일봉 엔드포인트(FHKST03010100)에서 그 값을 처음 검증한다.

출력: data/backfill/_probe-price-a2b-kis-sample.json (로컬 전용).
규칙 4(로컬 실행은 진단 전용, data/backfill 산출물 커밋 금지)에 따라 이
파일은 커밋하지 않는다 — 요약 수치는 별도 문서에 옮겨 적는다.
"""
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
A1B = REPO / "data" / "backfill" / "universe" / "a1b" / "delisted.jsonl"
CALENDAR = REPO / "data" / "backfill" / "calendar.json"
OUT = REPO / "data" / "backfill" / "_probe-price-a2b-kis-sample.json"
TOKEN_CACHE = REPO / ".token_cache_kis.json"

KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
PATH_DAILY = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
TR_DAILY = "FHKST03010100"

SEED = 20260816                # 오늘 날짜. 재현하려면 이 값 그대로 쓴다.
SAMPLE_SIZE = 40                # 30~50 지시 범위의 중간값
CONCURRENCY = 2
SLEEP_BETWEEN_CALLS = 0.15
MAX_PAGES_PER_TICKER = 34       # 측정된 천장 32 + 여유 2
MAX_RETRY_PER_CALL = 4          # EGW00201 지수 백오프 재시도 횟수


def stamp():
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def load_env():
    env = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip():
                env[k.strip()] = v.strip()
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


ENV = load_env()
KEY = ENV.get("KIS_APP_KEY", "")
SECRET = ENV.get("KIS_APP_SECRET", "")
TOKEN = None


def get_token():
    if TOKEN_CACHE.exists():
        try:
            c = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            exp = datetime.fromisoformat(c["expiresAt"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=KST)
            if exp - timedelta(minutes=10) > datetime.now(KST) and c.get("appKeyTail") == KEY[-4:]:
                print("  토큰: 캐시 재사용 (만료 " + c["expiresAt"] + ")")
                return c["accessToken"]
        except Exception:
            pass
    print("  토큰: 신규 발급")
    r = requests.post(BASE + "/oauth2/tokenP",
                      data=json.dumps({"grant_type": "client_credentials",
                                       "appkey": KEY, "appsecret": SECRET}),
                      headers={"content-type": "application/json"}, timeout=20)
    body = r.json()
    if r.status_code != 200 or "access_token" not in body:
        raise SystemExit("토큰 발급 실패")
    tok = body["access_token"]
    TOKEN_CACHE.write_text(json.dumps({
        "accessToken": tok,
        "expiresAt": body.get("access_token_token_expired", ""),
        "issuedAt": stamp(),
        "appKeyTail": KEY[-4:],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(TOKEN_CACHE, 0o600)
    except Exception:
        pass
    return tok


def call_daily_once(ticker, d1, d2):
    """1회 호출. 예외를 던지지 않고 결과 dict로 돌려준다 — 재시도는 호출부가 판단."""
    try:
        r = requests.get(
            BASE + PATH_DAILY,
            headers={"content-type": "application/json",
                     "authorization": "Bearer " + TOKEN,
                     "appkey": KEY, "appsecret": SECRET,
                     "tr_id": TR_DAILY, "custtype": "P"},
            params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker,
                    "FID_INPUT_DATE_1": d1, "FID_INPUT_DATE_2": d2,
                    "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"},
            timeout=15)
    except Exception as e:  # noqa: BLE001
        return {"http": None, "rtCd": None, "msgCd": None,
                "error": f"{type(e).__name__}: {str(e)[:150]}", "rows": {}}
    try:
        b = r.json()
    except Exception as e:  # noqa: BLE001
        return {"http": r.status_code, "rtCd": None, "msgCd": None,
                "error": f"{type(e).__name__}: {str(e)[:150]}", "rows": {}}
    o2 = b.get("output2") or []
    rows = {x.get("stck_bsop_date"): x for x in o2 if x.get("stck_bsop_date")}
    return {"http": r.status_code, "rtCd": b.get("rt_cd"), "msgCd": b.get("msg_cd"),
            "msg": (b.get("msg1") or "")[:120], "rows": rows}


def call_daily_with_retry(ticker, d1, d2, egw_counter):
    """EGW00201(초당 거래건수 초과)은 재시도 가능으로 분류한다(CLAUDE.md 운영기준).
    지수 백오프 최대 MAX_RETRY_PER_CALL회, 발생 횟수를 egw_counter에 누적한다."""
    r = None
    for attempt in range(MAX_RETRY_PER_CALL):
        r = call_daily_once(ticker, d1, d2)
        if r.get("msgCd") == "EGW00201":
            egw_counter["count"] += 1
            time.sleep(2 ** attempt)
            continue
        return r
    return r


def probe_ticker(ticker, frm, to):
    egw = {"count": 0}
    calls = []
    collected = {}
    cur_to = to
    t0 = time.time()
    status = "ok"
    for page in range(MAX_PAGES_PER_TICKER):
        r = call_daily_with_retry(ticker, frm, cur_to, egw)
        calls.append({"page": page, "d2": cur_to, "rowCount": len(r.get("rows") or {}),
                      "rtCd": r.get("rtCd"), "msgCd": r.get("msgCd")})
        if r.get("rtCd") != "0":
            status = "failed"   # 재시도 소진 후에도 정상 응답을 못 받음
            break
        if not r.get("rows"):
            break                # 정상 응답인데 빈 행 — 확정된 빈 응답(조회창 밖 폐지)
        collected.update(r["rows"])
        earliest = min(r["rows"])
        if earliest <= frm or len(r["rows"]) < 90:
            break
        cur_to = (datetime.strptime(earliest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        time.sleep(SLEEP_BETWEEN_CALLS)

    dates = sorted(collected)
    if status != "failed":
        status = "empty" if not collected else "ok"
    return {
        "ticker": ticker,
        "status": status,
        "callCount": len(calls),
        "rowCount": len(collected),
        "first": dates[0] if dates else None,
        "last": dates[-1] if dates else None,
        "egw00201Count": egw["count"],
        "elapsedSeconds": round(time.time() - t0, 1),
        "calls": calls,
    }


def main():
    global TOKEN
    if not KEY or not SECRET:
        raise SystemExit("KIS_APP_KEY / KIS_APP_SECRET 이 없다. .env를 본다.")

    candidates = []
    with open(A1B, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                candidates.append(json.loads(line))
    n = len(candidates)

    rng = random.Random(SEED)
    idx = sorted(rng.sample(range(n), SAMPLE_SIZE))
    sample = [candidates[i] for i in idx]

    cal = json.loads(CALENDAR.read_text(encoding="utf-8"))
    frm = cal["tradingDays"][0].replace("-", "")
    to = cal["tradingDays"][-1].replace("-", "")

    print(f"A2b KIS 표본 프로브 — 모집단 {n}건 중 {SAMPLE_SIZE}건 (seed={SEED}) · "
          f"동시성 {CONCURRENCY} · {frm}~{to}\n")
    print(f"  표본 인덱스: {idx}\n")

    TOKEN = get_token()

    started = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(probe_ticker, c["ticker"], frm, to): c for c in sample}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            print(f"  [{done}/{SAMPLE_SIZE}] {r['ticker']}: {r['status']:6s} · "
                  f"콜 {r['callCount']:2d} · 행 {r['rowCount']:5d} · "
                  f"EGW00201 {r['egw00201Count']}")

    elapsed = time.time() - started
    empties = [r for r in results if r["status"] == "empty"]
    ok = [r for r in results if r["status"] == "ok"]
    failed = [r for r in results if r["status"] == "failed"]
    egwTotal = sum(r["egw00201Count"] for r in results)

    summary = {
        "sampleSize": len(results),
        "emptyCount": len(empties),
        "emptyRate": round(len(empties) / len(results), 4) if results else None,
        "okCount": len(ok),
        "okAvgCalls": round(sum(r["callCount"] for r in ok) / len(ok), 2) if ok else None,
        "okAvgRows": round(sum(r["rowCount"] for r in ok) / len(ok), 1) if ok else None,
        "okMinCalls": min((r["callCount"] for r in ok), default=None),
        "okMaxCalls": max((r["callCount"] for r in ok), default=None),
        "failedCount": len(failed),
        "failedTickers": [r["ticker"] for r in failed],
        "totalCallsInSample": sum(r["callCount"] for r in results),
        "egw00201TotalHits": egwTotal,
        "wallClockSeconds": round(elapsed, 1),
    }

    out = {
        "probedAt": stamp(),
        "purpose": "A2b KIS 전체 적용 전 1단계 정찰 — 표본으로 콜 수 분포·"
                   "EGW00201·빈응답률 실측. A2b 코드·정책 무수정.",
        "population": n,
        "sampling": {"method": "random.Random(SEED).sample(range(population), SAMPLE_SIZE), "
                                "비복원, 이후 인덱스 오름차순 정렬",
                     "seed": SEED, "sampleSize": SAMPLE_SIZE, "indices": idx,
                     "tickers": [c["ticker"] for c in sample]},
        "concurrency": CONCURRENCY,
        "sleepBetweenCallsSeconds": SLEEP_BETWEEN_CALLS,
        "window": {"from": frm, "to": to},
        "summary": summary,
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"\n{'='*60}")
    er = summary["emptyRate"]
    print(f"표본 {summary['sampleSize']}건 · 빈응답 {summary['emptyCount']}건"
          f"({er*100 if er is not None else 0:.1f}%) · 실패 {summary['failedCount']}건")
    print(f"데이터 있는 종목({summary['okCount']}건) 평균 콜 수: {summary['okAvgCalls']} "
          f"(범위 {summary['okMinCalls']}~{summary['okMaxCalls']})")
    print(f"표본 총 호출량: {summary['totalCallsInSample']} · EGW00201 총 {egwTotal}회")
    print(f"실패 종목: {summary['failedTickers']}")
    print(f"소요: {summary['wallClockSeconds']}초")
    print(f"{'='*60}")
    print(f"\n{OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
