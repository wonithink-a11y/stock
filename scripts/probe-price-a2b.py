#!/usr/bin/env python3
"""A2b 커버리지 정찰 — 수집이 아니라 판정이다.

A1b 폐지 후보 1,222건에 대해 '가격을 받을 수 있는가'만 잰다. 산출물은 데이터가 아니라
커버리지와 실패 원인이며, 그 숫자가 A2b 계약과 A5의 coverage 게이트를 정한다.

왜 구현보다 먼저인가: 2026-08-05 실측에서 036720(한빛네트)의 2014~2026 조회가 0행이었다.
KRX 개별종목 일봉이 약 3,000거래일 롤링 윈도우라 그 이전 폐지분은 받을 경로 자체가 없다.
A5 게이트가 'A2b 존재 여부'로 남으면 A2b가 후보의 일부만 담아도 통과하고, 게이트가
있다는 사실이 편향이 없다는 뜻이 되어버린다. 확인해야 할 것은 존재가 아니라 확보율이다.

산출물 구성 — 게이트에 연결될 수치와 설계용 관측치를 분리한다(A2a에서 rollingWindowLoss를
관측 전용으로 강등한 것과 같은 철학):
  1차   커버리지 · 실패 원인 분해
  관측   dartModifyDate 분포(폐지연도 아님) · 최초/최종 거래일 분포 · 시장 구분 가용성

출력: data/backfill/_probe-price-a2b.json
정찰은 어떤 결과든 exit 0으로 끝낸다 — 판정이 산출물이다.
"""
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

A1B = "data/backfill/universe/a1b/delisted.jsonl"
CALENDAR = "data/backfill/calendar.json"
POLICY = "config/policies/price.v1.json"
OUT = "data/backfill/_probe-price-a2b.json"
KST = timezone(timedelta(hours=9))

# dartModifyDate는 폐지일이 아니다. 2019년에 폐지된 회사라도 2024년에 DART 레코드가
# 수정되면 2024로 집계된다. 분포는 운영 통계로만 읽고, 커버리지 해석의 축으로 쓰지 않는다.
DART_DATE_CAVEAT = ("dartModifyDate는 DART 레코드 최종 수정일이지 폐지일이 아니다. "
                    "폐지 시점과 인과관계가 보장되지 않으므로 '연도별 폐지 성공률'로 "
                    "읽으면 안 된다. 운영 통계·분포 관찰용이다.")


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main() -> int:
    from pykrx import stock

    if not os.path.exists(A1B):
        print(f"{A1B} 없음 — A1b를 먼저 실행하라")
        return 1
    pol = json.load(open(POLICY, encoding="utf-8"))
    cal = json.load(open(CALENDAR, encoding="utf-8"))
    cand = load_jsonl(A1B)
    frm = pol["collectFrom"].replace("-", "")
    to = cal["tradingDays"][-1].replace("-", "")

    print(f"A2b 커버리지 정찰 — 후보 {len(cand)}건 · 구간 {frm}~{to}")
    print(f"  (수집 아님. 각 종목 1회 조회로 '받을 수 있는가'만 판정한다)\n")

    ok, fail = [], []
    t0 = time.time()
    for i, c in enumerate(cand, 1):
        tk = c["ticker"]
        try:
            df = stock.get_market_ohlcv_by_date(frm, to, tk,
                                                adjusted=pol["source"]["adjusted"])
            if df is None or df.empty:
                # 창구 밖 폐지와 '지원하지 않는 티커'는 응답만으로 구분되지 않는다.
                # 구분 불가라는 사실 자체를 분류명에 남긴다.
                fail.append({**c, "reason": "EMPTY_ALL_WINDOW"})
            else:
                ok.append({**c, "rows": len(df),
                           "firstTraded": df.index[0].strftime("%Y-%m-%d"),
                           "lastTraded": df.index[-1].strftime("%Y-%m-%d")})
        except Exception as e:  # noqa: BLE001
            fail.append({**c, "reason": "EXCEPTION",
                         "error": f"{type(e).__name__}: {str(e)[:200]}"})
        if i % 200 == 0:
            print(f"  {i}/{len(cand)} · 성공 {len(ok)} · 실패 {len(fail)} · "
                  f"{time.time()-t0:.0f}s")
        time.sleep(pol["requestSleepSeconds"])

    n = len(cand)
    coverage = {
        "candidates": n,
        "success": len(ok),
        "fail": len(fail),
        "coverageRate": round(len(ok) / n, 4) if n else 0,
    }

    breakdown = Counter(f["reason"] for f in fail)
    exc_types = Counter(f.get("error", "").split(":")[0]
                        for f in fail if f["reason"] == "EXCEPTION")

    # ── 관측치 (설계 판단용, 게이트 아님) ──────────────────────
    by_dart_year = defaultdict(lambda: {"success": 0, "fail": 0})
    for r in ok:
        by_dart_year[(r.get("dartModifyDate") or "????")[:4]]["success"] += 1
    for r in fail:
        by_dart_year[(r.get("dartModifyDate") or "????")[:4]]["fail"] += 1
    for y, v in by_dart_year.items():
        t = v["success"] + v["fail"]
        v["rate"] = round(v["success"] / t, 4) if t else 0

    first_year = Counter(r["firstTraded"][:4] for r in ok)
    last_year = Counter(r["lastTraded"][:4] for r in ok)
    rows_dist = Counter()
    for r in ok:
        b = ("1-99" if r["rows"] < 100 else "100-499" if r["rows"] < 500
             else "500-999" if r["rows"] < 1000 else "1000+")
        rows_dist[b] += 1

    # 시장 구분 가용성 — A1b 레코드에 market이 없다. 폐지 종목의 시장을 얻는 경로가
    # 있는지 여기서 한 번 재고, 없으면 '측정 불가'로 남긴다(추정하지 않는다).
    market = {"available": False, "reason": None}
    try:
        lst = stock.get_market_ticker_list(cal["tradingDays"][-1].replace("-", ""),
                                           market="KOSPI")
        if lst:
            covered = sum(1 for r in ok if r["ticker"] in set(lst))
            market = {"available": True,
                      "note": "bulk 티커 목록이 열렸으나 현재 상장분만 담긴다 — "
                              "폐지 종목의 시장 구분에는 쓸 수 없다",
                      "delistedFoundInCurrentKospiList": covered}
        else:
            market = {"available": False, "reason": "빈 목록"}
    except Exception as e:  # noqa: BLE001
        market = {"available": False,
                  "reason": f"{type(e).__name__}: {str(e)[:150]}"}

    out = {
        "probedAt": datetime.now(KST).isoformat(),
        "stage": "A2b-probe",
        "purpose": "커버리지 판정. 수집이 아니며 가격 데이터를 남기지 않는다",
        "window": {"from": frm, "to": to,
                   "note": "KRX 개별종목 일봉은 약 3,000거래일 롤링 윈도우다. "
                           "그 이전 폐지분은 경로 자체가 없다"},

        "coverage": coverage,
        "failureBreakdown": dict(breakdown),
        "failureExceptionTypes": dict(exc_types),
        "failureNote": "EMPTY_ALL_WINDOW는 '창구 밖 폐지'와 '지원하지 않는 티커'를 "
                       "구분하지 못한다 — 응답이 둘 다 빈 결과이기 때문이다. "
                       "구분하려면 폐지일이 필요한데 A1b는 그것을 모른다(exitAt 전건 null).",

        "observations": {
            "dartModifyDateCaveat": DART_DATE_CAVEAT,
            "byDartModifyYear": dict(sorted(by_dart_year.items())),
            "firstTradedYear": dict(sorted(first_year.items())),
            "lastTradedYear": dict(sorted(last_year.items())),
            "rowsDistribution": dict(rows_dist),
            "marketClassification": market,
        },

        "samples": {
            "success": ok[:20],
            "fail": fail[:20],
        },
        "elapsedSeconds": round(time.time() - t0, 1),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"A1b 후보        {coverage['candidates']:>6}")
    print(f"가격 조회 성공   {coverage['success']:>6}")
    print(f"가격 조회 실패   {coverage['fail']:>6}")
    print(f"커버리지        {coverage['coverageRate']*100:>6.1f}%")
    print(f"{'='*60}")
    print(f"\n실패 원인: {dict(breakdown)}")
    if exc_types:
        print(f"  예외 유형: {dict(exc_types)}")
    print(f"\n[관측] 최초 거래일 연도: {dict(sorted(first_year.items()))}")
    print(f"[관측] 최종 거래일 연도: {dict(sorted(last_year.items()))}")
    print(f"[관측] 행수 분포: {dict(rows_dist)}")
    print(f"[관측] 시장 구분: {market}")
    print(f"\n{OUT} ({out['elapsedSeconds']}s)")
    return 0


if __name__ == "__main__":
    # 정찰은 판정이 산출물이다. 어떤 결과든 exit 0으로 끝낸다.
    try:
        main()
    except KeyboardInterrupt:
        print("중단됨")
    sys.exit(0)
