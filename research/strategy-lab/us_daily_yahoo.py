"""미국 지수·ETF·거시 대용 일봉 전 기간 캐시 (야후 공개 차트, 무료·비공식). 놀이터·탐색 공용.

  python research/strategy-lab/us_daily_yahoo.py            # 없는 것만 받는다
  python research/strategy-lab/us_daily_yahoo.py --refresh  # 전부 다시
  from us_daily_yahoo import load; load("^GSPC")             # DataFrame(date index: open high low close adjclose volume)

저장: data/us-daily/<기호>.parquet (gitignore). 재배포 금지 자료라 커밋하지 않는다.
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent / "data" / "us-daily"
SYMS = ["^GSPC", "^NDX", "^DJI", "^RUT", "^VIX", "^VIX3M", "^VIX9D", "^VVIX", "^SKEW", "^TNX", "^IRX", "^TYX",
        "SPY", "QQQ", "IWM", "DIA", "TLT", "IEF", "SHY", "HYG", "LQD", "GLD", "SLV", "USO", "UUP", "EEM", "EFA", "EWY",
        "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC", "SMH", "SOXX",
        "BTC-USD", "ETH-USD", "DX-Y.NYB", "CL=F", "GC=F", "HG=F", "KRW=X", "^KS11", "^KQ11"]


def fetch(sym):
    url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}"
           f"?period1=0&period2={int(time.time())}&interval=1d&events=div%2Csplit&includeAdjustedClose=true")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
        res = json.load(r)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    df = pd.DataFrame({"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
                       "adjclose": adj if adj else q["close"], "volume": q.get("volume")},
                      index=pd.to_datetime(res["timestamp"], unit="s").normalize())
    df.index.name = "date"
    return df.dropna(subset=["close"]).groupby(level=0).last()


def load(sym):
    return pd.read_parquet(OUT / f"{sym}.parquet")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    refresh = "--refresh" in sys.argv
    for s in SYMS:
        f = OUT / f"{s}.parquet"
        if f.exists() and not refresh:
            continue
        try:
            d = fetch(s)
            d.to_parquet(f)
            print(f"{s}: {d.index.min().date()}~{d.index.max().date()} {len(d)}행", flush=True)
        except Exception as e:                      # 하나 실패가 나머지를 막지 않는다
            print(f"{s}: 실패 {type(e).__name__} {e}", flush=True)
        time.sleep(0.5)
