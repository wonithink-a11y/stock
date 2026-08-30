#!/usr/bin/env python
"""Step 16 — Binance OI historical 데이터 감사 (올바른 /futures/data 경로).

대량 다운로드 금지 원칙에 따라 소량의 프로브 요청만 실행한다.
"""
import datetime
import requests

BASE = "https://fapi.binance.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def t(ms):
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.timezone.utc).isoformat()


def probe(label, path, params):
    r = requests.get(BASE + path, params=params, headers=UA, timeout=30)
    if r.status_code != 200:
        print(label, "-> status=", r.status_code, " head=", repr(r.text[:100]))
        return None
    try:
        j = r.json()
    except Exception:
        print(label, "-> NOT-JSON status=200", repr(r.text[:120]))
        return None
    if isinstance(j, dict) and "code" in j:
        print(label, "-> API-ERR", j)
        return None
    n = len(j)
    if n:
        print(label, ": n=", n, " first=", t(j[0]["timestamp"]), " last=", t(j[-1]["timestamp"]))
        k = list(j[0].keys())
        print("      keys=", k, " sumOI=", j[0].get("sumOpenInterest"), " sumOIV=", j[0].get("sumOpenInterestValue"))
    else:
        print(label, ": n=0 (EMPTY)")
    return j


if __name__ == "__main__":
    P = "/futures/data/openInterestHist"
    print("### A. 기준 확인: 최근 30일 윈도우 (no startTime)")
    probe("BTCUSDT 1h (recent)", P, {"symbol": "BTCUSDT", "period": "1h", "limit": 500})
    probe("BTCUSDT 5m (recent)", P, {"symbol": "BTCUSDT", "period": "5m", "limit": 500})
    probe("BTCUSDT 1d (recent)", P, {"symbol": "BTCUSDT", "period": "1d", "limit": 500})

    print("\n### B. 과거 윈도우 확보 가능 여부 (startTime/endTime)")
    probe("2026-08-04~06 (3주전)", P, {"symbol": "BTCUSDT", "period": "1h", "limit": 500,
                                       "startTime": 1754316000000, "endTime": 1754496000000})
    probe("2026-07-01~02 (8주전)", P, {"symbol": "BTCUSDT", "period": "1h", "limit": 500,
                                       "startTime": 1751328000000, "endTime": 1751500800000})
    probe("2025-01-01 (1.6년전)", P, {"symbol": "BTCUSDT", "period": "1d", "limit": 500,
                                      "startTime": 1735686000000, "endTime": 1736031600000})
    probe("2023-05-21 (스터디시작)", P, {"symbol": "BTCUSDT", "period": "1d", "limit": 500,
                                         "startTime": 1684635600000, "endTime": 1685232000000})
    probe("2021-06-01 (사전기간)", P, {"symbol": "BTCUSDT", "period": "1d", "limit": 500,
                                       "startTime": 1622505600000, "endTime": 1622937600000})

    print("\n### C. 종목별 coverage (2026-08 최근윈도우 + 2023-05)")
    for sym in ["BTCUSDT", "ETHUSDT", "NEARUSDT", "OPUSDT", "UNIUSDT", "SOLUSDT"]:
        probe(sym + " recent 1h", P, {"symbol": sym, "period": "1h", "limit": 30})
    for sym in ["NEARUSDT", "OPUSDT", "UNIUSDT"]:
        probe(sym + " 2023-05-21 (1d)", P, {"symbol": sym, "period": "1d", "limit": 500,
                                            "startTime": 1684635600000, "endTime": 1685232000000})

    print("\n### D. 추가 공개 OI 관련 엔드포인트 존재 확인")
    probe("openInterest now (fapi/v1)", "/fapi/v1/openInterest", {"symbol": "BTCUSDT"})
    probe("basis", "/futures/data/basis", {"symbol": "BTCUSDT", "period": "1d", "limit": 500,
                                           "startTime": 1684635600000, "endTime": 1685232000000})
    probe("takerlongshortRatio", "/futures/data/takerlongshortRatio", {"symbol": "BTCUSDT", "period": "1d", "limit": 500,
                                                                       "startTime": 1684635600000, "endTime": 1685232000000})