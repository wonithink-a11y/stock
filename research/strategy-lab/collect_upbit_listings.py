#!/usr/bin/env python3
"""업비트 원화 마켓 상장일 + 바이낸스 USDT 일봉 — 사전등록 findings/upbit-krw-listing-preregistration-2026-10.md 의 재료.

공개 API 만 쓴다(키 없음). 저장(gitignore): data/crypto/upbit-listings/
  upbit_krw_daily/<KRW-XXX>.parquet  업비트 원화 일봉 전체(첫 봉 = 상장일)
  binance_daily/<XXXUSDT>.parquet    바이낸스 현물 일봉(상장일 −40일부터 1000일)
  listings.json                      시장·첫 봉 날짜·바이낸스 유무
현재 거래 중인 원화 시장만 나온다(업비트 API 는 폐지 시장을 주지 않는다 — 생존편향, 결과 문서에 적는다).
    python research/strategy-lab/collect_upbit_listings.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "crypto" / "upbit-listings"
UP = "https://api.upbit.com/v1"
BN = "https://api.binance.com/api/v3/klines"


def get(url, params):
    for k in range(5):
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 429:
            time.sleep(1 + k)
            continue
        if r.status_code == 400 and "binance" in url:
            return None                      # 그런 심볼 없음
        r.raise_for_status()
        return r.json()
    raise SystemExit(f"요청 실패 {url} {params}")


def upbit_daily(market: str) -> pd.DataFrame:
    rows, to = [], None
    while True:
        p = {"market": market, "count": 200, **({"to": to} if to else {})}
        js = get(f"{UP}/candles/days", p)
        time.sleep(0.12)
        rows += js
        if len(js) < 200:
            break
        to = js[-1]["candle_date_time_utc"] + "Z"
    d = pd.DataFrame(rows)[["candle_date_time_utc", "opening_price", "trade_price", "candle_acc_trade_price"]]
    d["date"] = pd.to_datetime(d["candle_date_time_utc"])
    return d.drop(columns="candle_date_time_utc").drop_duplicates("date").sort_values("date").reset_index(drop=True)


def binance_daily(sym: str, start: pd.Timestamp) -> pd.DataFrame | None:
    js = get(BN, {"symbol": sym, "interval": "1d", "startTime": int(start.timestamp() * 1000), "limit": 1000})
    time.sleep(0.1)
    if not js:
        return None
    d = pd.DataFrame(js).iloc[:, :6]
    d.columns = ["t", "open", "high", "low", "close", "volume"]
    d["date"] = pd.to_datetime(d["t"], unit="ms")
    for c in ("open", "high", "low", "close", "volume"):
        d[c] = d[c].astype(float)
    return d.drop(columns="t")


def main():
    (OUT / "upbit_krw_daily").mkdir(parents=True, exist_ok=True)
    (OUT / "binance_daily").mkdir(parents=True, exist_ok=True)
    mk = [m["market"] for m in get(f"{UP}/market/all", {}) if m["market"].startswith("KRW-")]
    meta = {}
    for i, m in enumerate(sorted(mk), 1):
        f = OUT / "upbit_krw_daily" / f"{m}.parquet"
        d = pd.read_parquet(f) if f.exists() else upbit_daily(m)
        d.to_parquet(f, index=False)
        first = d["date"].iloc[0]
        sym = m.split("-", 1)[1] + "USDT"
        bf = OUT / "binance_daily" / f"{sym}.parquet"
        has = bf.exists()
        if not has and first >= pd.Timestamp("2018-01-01"):
            b = binance_daily(sym, first - pd.Timedelta(days=40))
            if b is not None and len(b):
                b.to_parquet(bf, index=False)
                has = True
        meta[m] = {"first": first.date().isoformat(), "binance": sym if has else None}
        print(f"[{i}/{len(mk)}] {m} {first.date()} {'B' if has else '-'}", flush=True)
    # 1000일씩 오늘까지(첫 실행은 세 번만 받아 2025-10-18 이후가 비었다 — 2026-10-18 수정)
    starts = pd.date_range("2017-08-01", pd.Timestamp.today(), freq="999D")
    btc = pd.concat([binance_daily("BTCUSDT", s) for s in starts])
    btc.drop_duplicates("date").to_parquet(OUT / "binance_daily" / "BTCUSDT.parquet", index=False)
    (OUT / "listings.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("listings", len(meta), "binance", sum(v["binance"] is not None for v in meta.values()))


if __name__ == "__main__":
    main()
