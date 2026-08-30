#!/usr/bin/env python
"""Step 16 — Binance 접근 진단: 도메인/엔드포인트/헤더별 실제 응답 확인."""
import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

PROBES = [
    ("fapi exchangeInfo", "https://fapi.binance.com/fapi/v1/exchangeInfo", {}),
    ("fapi fundingRate", "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3", {}),
    ("fapi openInterestHist", "https://fapi.binance.com/fapi/v1/openInterestHist?symbol=BTCUSDT&period=1h&limit=3", {}),
    ("fapi openInterestHist+UA", "https://fapi.binance.com/fapi/v1/openInterestHist?symbol=BTCUSDT&period=1h&limit=3", UA),
    ("fapi klines", "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1d&limit=3", {}),
    ("api exchangeInfo", "https://api.binance.com/api/v3/exchangeInfo", {}),
]


def check(label, url, headers):
    try:
        r = requests.get(url, headers=headers, timeout=30)
        ct = r.headers.get("Content-Type", "??")
        body = r.text
        head = body[:120].replace("\n", " ")
        verdict = "OK-JSON" if body.strip().startswith(("[", "{")) else "NOT-JSON"
        print(f"{label:32s} status={r.status_code} ct={ct[:40]} {verdict} :: {head}")
    except Exception as e:
        print(f"{label:32s} EXC {e}")


for label, url, h in PROBES:
    check(label, url, h)