#!/usr/bin/env python3
"""A2b 대체경로 ③ 프로브 — KRX-native 개별종목시세(adjStkPrc=2)가 Naver 우회 없이
2014~현재 전 구간·수정주가를 주는지 소수 종목으로 확인한다 (수집 아님).

배경(docs/control/세션인수인계-2026-08-16.md §4): pykrx의 고수준
stock.get_market_ohlcv_by_date(adjusted=True)는 KRX가 아니라 Naver Finance로
가고, Naver는 요청 구간과 무관하게 "오늘 기준 최근 3,000캔들"만 준다.
pykrx.website.krx.market.wrap.get_market_ohlcv_by_date()는 같은 인증 계열
(KRX_ID/KRX_PW)로 KRX 개별종목시세(adjStkPrc=2)를 직접 호출한다 — 이 경로가
①3,000캔들 캡이 없는지 ②정말 수정주가인지 ③분할 종목에서 연속적인지가
미확인이라 이 프로브가 먼저다.

확인 항목 (인수인계 §4의 5개, 순서 동일):
  1. 2014~현재 전체 기간을 반환하는가
  2. 실제 반환 행수·시작일/종료일
  3. 반환값이 수정주가인가(adjusted=True/False 대조)
  4. 3,000캔들 제한이 이 경로에도 있는가
  5. 005930(2018-05 액면분할) 전후 가격 연속성

출력: data/backfill/_probe-price-a2b-krx-native.json
정찰은 판정이 산출물이다 — 어떤 결과든 exit 0.
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

CALENDAR = "data/backfill/calendar.json"
OUT = "data/backfill/_probe-price-a2b-krx-native.json"
KST = timezone(timedelta(hours=9))

# 005930: 2018-05-04 액면분할(50:1) 이력 — 연속성 판정용. 000660: 분할 이력 없는 대조군.
TICKERS = ["005930", "000660"]
SPLIT_WINDOW = ("20180420", "20180511")  # 005930 분할 전후 5거래일씩


def _row_dates(df):
    return {"rows": len(df),
            "first": df.index[0].strftime("%Y-%m-%d") if not df.empty else None,
            "last": df.index[-1].strftime("%Y-%m-%d") if not df.empty else None}


def main() -> int:
    from pykrx.website.krx.market.wrap import get_market_ohlcv_by_date as krx_native

    cal = json.load(open(CALENDAR, encoding="utf-8"))
    frm = cal["tradingDays"][0].replace("-", "")
    to = cal["tradingDays"][-1].replace("-", "")

    print(f"KRX-native 개별종목시세 프로브 — {TICKERS} · {frm}~{to}\n")

    results = {}
    for tk in TICKERS:
        entry = {}
        for label, adjusted in (("adjusted", True), ("raw", False)):
            try:
                t0 = time.time()
                df = krx_native(frm, to, tk, adjusted=adjusted)
                info = _row_dates(df)
                info["elapsedSeconds"] = round(time.time() - t0, 1)
                entry[label] = info
            except Exception as e:  # noqa: BLE001
                entry[label] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            time.sleep(1)

        if tk == "005930" and not entry.get("adjusted", {}).get("error"):
            try:
                w = krx_native(*SPLIT_WINDOW, tk, adjusted=True)
                entry["splitContinuity"] = {
                    "rows": len(w),
                    "closes": {d.strftime("%Y-%m-%d"): int(row["종가"])
                              for d, row in w.iterrows()},
                }
            except Exception as e:  # noqa: BLE001
                entry["splitContinuity"] = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            time.sleep(1)

        results[tk] = entry
        print(f"  {tk}: {entry}")

    out = {
        "probedAt": datetime.now(KST).isoformat(),
        "purpose": "A2b 대체경로 ③(KRX-native adjStkPrc=2) 소수종목 프로브 — 수집 아님, "
                   "가격 데이터를 남기지 않는다(요약 통계만)",
        "window": {"from": frm, "to": to,
                   "note": "3,000캔들 캡이 없다면 rows가 요청 구간 전체 거래일수에 근접해야 한다"},
        "splitWindow": SPLIT_WINDOW,
        "results": results,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n{OUT}")
    return 0


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("중단됨")
    sys.exit(0)
