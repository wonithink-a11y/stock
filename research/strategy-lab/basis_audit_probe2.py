#!/usr/bin/env python
"""Step 17 follow-up — pair 파라미터 보정 probe."""
import requests

BASE = "https://fapi.binance.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
T_2019 = 1568044800000
T_2020 = 1600473600000
T_2023 = 1684635600000
T_NOW = 1787976000000


def probe(label, path, params):
    r = requests.get(BASE + path, params=params, headers=UA, timeout=30)
    body = r.text
    if body.strip().startswith("["):
        import json
        j = json.loads(body)
        print(label, ": OK n=", len(j), end="")
        if j:
            first = j[0]
            if isinstance(first, list):
                print(" row0_head=", first[:6], " first_open=", first[0], " last_open=", j[-1][0])
            else:
                print(" keys=", list(first.keys()), " first=", first)
        else:
            print(" : EMPTY")
        return
    print(label, ": ", body[:220])


if __name__ == "__main__":
    print("### indexPriceKlines (pair)")
    probe("Ipk BTC 1h now", "/fapi/v1/indexPriceKlines",
          {"pair": "BTCUSDT", "interval": "1h", "limit": 3})
    probe("Ipk BTC 4h 2023-05", "/fapi/v1/indexPriceKlines",
          {"pair": "BTCUSDT", "interval": "4h", "limit": 3, "startTime": T_2023})
    probe("Ipk BTC 1d 2019", "/fapi/v1/indexPriceKlines",
          {"pair": "BTCUSDT", "interval": "1d", "limit": 3, "startTime": T_2019})
    probe("Ipk UNI 1d 2020-09", "/fapi/v1/indexPriceKlines",
          {"pair": "UNIUSDT", "interval": "1d", "limit": 3, "startTime": T_2020})
    probe("Ipk NEAR 1d 2023", "/fapi/v1/indexPriceKlines",
          {"pair": "NEARUSDT", "interval": "1d", "limit": 3, "startTime": T_2023})

    print("\n### basis (pair) — 30일 한계 확인")
    probe("basis BTC 1d recent", "/futures/data/basis",
          {"pair": "BTCUSDT", "period": "1d", "limit": 3})
    probe("basis BTC 1d 2023-05", "/futures/data/basis",
          {"pair": "BTCUSDT", "period": "1d", "limit": 3,
           "startTime": T_2023, "endTime": T_2023 + 3 * 86400000})
    probe("basis BTC 1d 60일전", "/futures/data/basis",
          {"pair": "BTCUSDT", "period": "1d", "limit": 3,
           "startTime": T_NOW - 60 * 86400000, "endTime": T_NOW - 59 * 86400000})
    probe("basis UNI 1d recent", "/futures/data/basis",
          {"pair": "UNIUSDT", "period": "1d", "limit": 3})