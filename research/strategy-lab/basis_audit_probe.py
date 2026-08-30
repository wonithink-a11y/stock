#!/usr/bin/env python
"""Step 17 — Binance USDS-M Basis / Premium Index data 감사 프로브 (경량).

대량 다운로드 금지 원칙: 소량(limit<=3~5) 요청만으로 존재·coverage·해상도 확인.
"""
import requests

BASE = "https://fapi.binance.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# 검증할 타임 기준점 (UTC ms)
T_2019 = 1568044800000   # 2019-09-10
T_2020 = 1600473600000   # 2020-09-19 (UNI 상장근처)
T_2021 = 1622505600000   # 2021-06-01
T_2022 = 1654041600000   # 2022-06-01 (OP 상장근처)
T_2023 = 1684635600000   # 2023-05-21 (스터디 시작)
T_NOW = 1787976000000    # 2026-08-29부근


def probe(label, path, params, nktty=4):
    try:
        r = requests.get(BASE + path, params=params, headers=UA, timeout=30)
    except Exception as e:
        print(label, "-> EXC", e)
        return
    body = r.text
    if body.strip().startswith("["):
        import json
        j = json.loads(body)
        print(label, ": OK n=", len(j), end="")
        if j:
            first = j[0]
            last = j[-1]
            if isinstance(first, list):
                print(" row0=", first[:6], end="")
                print(" first_open=", first[0], " last_open=", last[0])
            else:
                print(" keys=", list(first.keys()), end="")
                print(" first=", first.get("openTime", first.get("timestamp", "?")),
                      " last=", last.get("openTime", last.get("timestamp", "?")))
        else:
            print()
        return
    if body.strip().startswith("{"):
        print(label, ": DICT", body[:180])
        return
    print(label, ": status=", r.status_code, " body=", body[:120])


def mpk(sym, iv, start, end=None, limit=3):
    p = {"symbol": sym, "interval": iv, "limit": limit}
    if start:
        p["startTime"] = start
    if end:
        p["endTime"] = end
    probe(sym + " " + iv + " t=" + str(start or "now"), "/fapi/v1/markPriceKlines", p)


def ipk(sym, iv, start, end=None, limit=3):
    p = {"symbol": sym, "interval": iv, "limit": limit}
    if start:
        p["startTime"] = start
    if end:
        p["endTime"] = end
    probe(sym + " " + iv + " t=" + str(start or "now"), "/fapi/v1/indexPriceKlines", p)


if __name__ == "__main__":
    print("### 1. premiumIndex (현재 스냅샷)")
    probe("premiumIndex BTC", "/fapi/v1/premiumIndex", {"symbol": "BTCUSDT"})

    print("\n### 2. markPriceKlines historical")
    mpk("BTCUSDT", "1h", None)
    mpk("BTCUSDT", "1h", T_2019)
    mpk("BTCUSDT", "4h", T_2023)
    mpk("BTCUSDT", "1d", T_2021)

    print("\n### 3. indexPriceKlines historical")
    ipk("BTCUSDT", "1h", None)
    ipk("BTCUSDT", "4h", T_2023)
    ipk("BTCUSDT", "1d", T_2019)

    print("\n### 4. 알트 historical coverage")
    for sym, t in [("UNIUSDT", T_2020), ("OPUSDT", T_2022), ("NEARUSDT", T_2023), ("SOLUSDT", T_2023)]:
        mpk(sym, "1d", t)
    ipk("UNIUSDT", "1d", T_2020)

    print("\n### 5. basis (futures/data/basis) — 30일 한계 확인")
    probe("basis recent", "/futures/data/basis", {"symbol": "BTCUSDT", "period": "1h", "limit": 3})
    probe("basis 60일전", "/futures/data/basis", {"symbol": "BTCUSDT", "period": "1h", "limit": 3,
                                                  "startTime": T_NOW - 60 * 24 * 3600000,
                                                  "endTime": T_NOW - 59 * 24 * 3600000})
    probe("basis 2023-05", "/futures/data/basis", {"symbol": "BTCUSDT", "period": "1d", "limit": 3,
                                                   "startTime": T_2023, "endTime": T_2023 + 3 * 86400000})

    print("\n### 6. 해상도 확인 (period 아님 — markPriceKlines interval)")
    mpk("BTCUSDT", "1m", None)