#!/usr/bin/env python
"""Step 16 — openInterestHist 한계 정밀 확인: startTime 수용 경계.
20초 이내, 소량 요청만 사용."""
import requests

BASE = "https://fapi.binance.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def probe(label, params):
    r = requests.get(BASE + "/futures/data/openInterestHist", params=params, headers=UA, timeout=30)
    body = r.text
    if body.strip().startswith("["):
        import json
        j = json.loads(body)
        print(label, ": OK n=", len(j), end="")
        if j:
            print(" first=", j[0]["timestamp"], " last=", j[-1]["timestamp"])
        else:
            print()
        return "OK"
    print(label, ": status=", r.status_code, " body=", body[:160])
    return "ERR"


if __name__ == "__main__":
    now = 1787976000000  # 대략 2026-08-29 04:00Z (그리드 정렬 기준치로 사용)
    H = 3600000
    print("startTime 그리드 정렬(정각) 최근 지점: t0 =", now % H == 0, now, (now - 8 * H) % H == 0)
    probe("recent aligned (now-8h)", {"symbol": "BTCUSDT", "period": "1h", "limit": 20,
                                      "startTime": now - 8 * H})
    probe("25일 전 (30일 내)", {"symbol": "BTCUSDT", "period": "1h", "limit": 20,
                               "startTime": now - 25 * 24 * H})
    probe("30일 전 경계", {"symbol": "BTCUSDT", "period": "1h", "limit": 20,
                          "startTime": now - 30 * 24 * H})
    probe("31일 전 (범위 밖)", {"symbol": "BTCUSDT", "period": "1h", "limit": 20,
                              "startTime": now - 31 * 24 * H})
    probe("60일 전", {"symbol": "BTCUSDT", "period": "1d", "limit": 20,
                     "startTime": now - 60 * 24 * H})
    probe("2년 전(2024-08)", {"symbol": "BTCUSDT", "period": "1d", "limit": 20,
                             "startTime": 1723708800000})