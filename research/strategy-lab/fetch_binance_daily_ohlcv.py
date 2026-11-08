#!/usr/bin/env python3
"""바이낸스 현물 일봉(OHLCV, 거래량 포함) 수집 — 커뮤니티 전략 재검증(crypto-community-replication)용.
공개 시세 API(키 없음). 기존 data/crypto/daily-binance 는 거래량이 없어 따로 받는다. 저장: data/crypto/daily-binance-ohlcv/<SYM>.parquet
(index = 일봉 UTC 0시, 열 open high low close volume). 오늘(미완성) 봉은 버린다.   python research/strategy-lab/fetch_binance_daily_ohlcv.py
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).resolve().parent / "data" / "crypto" / "daily-binance-ohlcv"
SYMS = ["BTCUSDT", "ETHUSDT", "AAVEUSDT", "ADAUSDT", "APTUSDT", "ARBUSDT", "ATOMUSDT", "AVAXUSDT", "BCHUSDT", "BNBUSDT", "DOGEUSDT", "DOTUSDT", "FILUSDT", "FTTUSDT", "INJUSDT", "LINKUSDT",
        "LTCUSDT", "LUNAUSDT", "NEARUSDT", "OPUSDT", "PEPEUSDT", "SHIBUSDT", "SOLUSDT", "SUIUSDT", "TRXUSDT", "UNIUSDT", "WLDUSDT", "XMRUSDT", "XRPUSDT", "ZECUSDT"]
START = int(pd.Timestamp("2020-10-01", tz="UTC").timestamp() * 1000)
END = pd.Timestamp("2026-11-06", tz="UTC")


def fetch(sym):
    rows, t = [], START
    while True:
        r = requests.get("https://api.binance.com/api/v3/klines", params=dict(symbol=sym, interval="1d", startTime=t, limit=1000), timeout=30)
        r.raise_for_status()
        k = r.json()
        if not k:
            break
        rows += k
        t = k[-1][0] + 86_400_000
        if len(k) < 1000:
            break
        time.sleep(0.15)
    if not rows:
        return None
    d = pd.DataFrame(rows).iloc[:, :6]
    d.columns = ["t", "open", "high", "low", "close", "volume"]
    d.index = pd.to_datetime(d["t"], unit="ms")
    d = d[["open", "high", "low", "close", "volume"]].astype(float)
    return d[d.index <= END.tz_localize(None)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {}
    for s in SYMS:
        d = fetch(s)
        if d is None:
            print(s, "자료 없음")
            continue
        f = OUT / f"{s}.parquet"
        d.to_parquet(f)
        meta[s] = dict(rows=len(d), start=str(d.index.min().date()), end=str(d.index.max().date()), sha256=hashlib.sha256(f.read_bytes()).hexdigest()[:16])
        print(s, meta[s])
    (OUT / "_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
