#!/usr/bin/env python3
"""연금계좌 시험용 미국 장기 이력 수집(yfinance, 키 불필요). 산출: data/pension-test/{티커}.parquet (gitignore).
auto_adjust=True — 총수익 지수로 쓴다(배당 재투자). 금리(^TYX·^TNX·^IRX)는 % 수준 그대로."""
import sys
from pathlib import Path
import pandas as pd, yfinance as yf

OUT = Path(__file__).resolve().parent / "data" / "pension-test"
TICKERS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY", "SPY", "TLT", "IEF", "SHY", "GLD",
           "^TYX", "^TNX", "^IRX", "KRW=X"]

for t in TICKERS:
    df = yf.Ticker(t).history(period="max", auto_adjust=True)
    if df.empty:
        sys.exit(f"{t}: 빈 응답")
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df[["Close"]].rename(columns={"Close": "close"}).to_parquet(OUT / f"{t.replace('^','_').replace('=','_')}.parquet")
    print(t, df.index[0].date(), df.index[-1].date(), len(df))
