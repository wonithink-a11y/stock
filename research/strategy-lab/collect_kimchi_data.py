"""김치 프리미엄 연구용 공개 자료 수집(키 불필요) — 업비트 KRW-BTC·KRW-ETH 일봉 · 바이낸스 BTCUSDT·ETHUSDT 일봉 · FRED DEXKOUS.

  python research/strategy-lab/collect_kimchi_data.py

저장(gitignore): data/kimchi/{upbit_KRW-BTC,upbit_KRW-ETH,binance_BTCUSDT,binance_ETHUSDT,dexkous}.parquet. 일봉 마감은 둘 다 00:00 UTC.
"""
import io
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "kimchi"
UA = {"User-Agent": "stock-research"}


def upbit(market):
    rows, to = [], None
    while True:
        p = {"market": market, "count": 200}
        if to:
            p["to"] = to
        r = requests.get("https://api.upbit.com/v1/candles/days", params=p, headers=UA, timeout=30)
        r.raise_for_status()
        js = r.json()
        if not js:
            break
        rows += js
        to = js[-1]["candle_date_time_utc"].replace("T", " ")
        if len(js) < 200:
            break
        time.sleep(0.2)
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["candle_date_time_utc"]).dt.normalize()
    return df[["date", "trade_price"]].rename(columns={"trade_price": "close"}).drop_duplicates("date").sort_values("date")


def binance(symbol):
    rows, start = [], int(pd.Timestamp("2017-08-01").timestamp() * 1000)
    while True:
        r = requests.get("https://api.binance.com/api/v3/klines", params={"symbol": symbol, "interval": "1d", "startTime": start, "limit": 1000}, headers=UA, timeout=30)
        r.raise_for_status()
        js = r.json()
        if not js:
            break
        rows += js
        start = js[-1][0] + 86400000
        if len(js) < 1000:
            break
        time.sleep(0.2)
    df = pd.DataFrame(rows).iloc[:, [0, 4]]
    df.columns = ["t", "close"]
    df["date"] = pd.to_datetime(df["t"], unit="ms").dt.normalize()
    df["close"] = df["close"].astype(float)
    return df[["date", "close"]]


def fred():
    r = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DEXKOUS", headers=UA, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "fx"]
    df["date"] = pd.to_datetime(df["date"])
    df["fx"] = pd.to_numeric(df["fx"], errors="coerce")
    return df.dropna()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for m in ("KRW-BTC", "KRW-ETH"):
        d = upbit(m)
        d.to_parquet(OUT / f"upbit_{m}.parquet", index=False)
        print(m, len(d), d["date"].min().date(), d["date"].max().date())
    for s in ("BTCUSDT", "ETHUSDT"):
        d = binance(s)
        d.to_parquet(OUT / f"binance_{s}.parquet", index=False)
        print(s, len(d), d["date"].min().date(), d["date"].max().date())
    d = fred()
    d.to_parquet(OUT / "dexkous.parquet", index=False)
    print("DEXKOUS", len(d), d["date"].min().date(), d["date"].max().date())


if __name__ == "__main__":
    main()
