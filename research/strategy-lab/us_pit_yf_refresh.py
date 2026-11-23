"""S&P500 PIT 생존 종목(raw/yf) 가격을 야후 공개 차트로 최신까지 다시 받는다 → raw/yf_refresh/ (원본 raw/yf 는 덮지 않는다).
close = 분할조정·배당 미조정(raw/yf 와 같은 정의). 비교 후 이어 붙이는 것은 패널 단계에서.
  python research/strategy-lab/us_pit_yf_refresh.py
"""
import time
from pathlib import Path
import pandas as pd
from us_daily_yahoo import fetch

RAW = Path(__file__).resolve().parent / "data" / "us-pit" / "raw"
OUT = RAW / "yf_refresh"
OUT.mkdir(parents=True, exist_ok=True)
syms = sorted(p.stem for p in (RAW / "yf").glob("*.parquet"))
bad = []
for i, s in enumerate(syms, 1):
    f = OUT / f"{s}.parquet"
    if f.exists():
        continue
    try:
        d = fetch(s.replace(".", "-"))
        d.to_parquet(f)
    except Exception as e:
        bad.append((s, type(e).__name__))
    time.sleep(0.4)
    if i % 50 == 0:
        print(f"{i}/{len(syms)} 실패 {len(bad)}", flush=True)
print(f"끝 {len(syms)} · 실패 {len(bad)}: {bad[:20]}")
