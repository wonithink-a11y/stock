"""V6 사전 추출: 원본 A4 백필(jsonl.gz)에서 외국인+기관 매수 금액/수량만 뽑아 캐시.

읽기 전용 원본: data/backfill/supplyDemand/a4/{year}.jsonl.gz
캐시(쓰기 허용 영역): research/strategy-lab/.cache/v6_acc_price/{year}.parquet

외국인 = 외국인 + 기타외국인 (a4 데이터셋 관례)
기관   = 금융투자+보험+투신+사모+은행+기타금융+연기금+기타법인 (동일 관례)

  python v6_extract_buy_vwap.py
"""
import gzip
import json
import os
import time

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(REPO_ROOT, "data", "backfill", "supplyDemand", "a4")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "v6_acc_price")

FOREIGN = ["외국인", "기타외국인"]
INST = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금", "기타법인"]


def num(d, keys):
    t = 0
    for k in keys:
        v = d.get(k)
        if v:
            t += v
    return int(t)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for year in range(2016, 2027):
        out_path = os.path.join(OUT_DIR, f"{year}.parquet")
        if os.path.exists(out_path):
            print("skip existing:", year)
            continue
        src = os.path.join(SRC_DIR, f"{year}.jsonl.gz")
        if not os.path.exists(src):
            print("missing source:", year)
            continue
        t0 = time.time()
        rows = []
        with gzip.open(src, "rt", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                ba, bv = d["buyAmount"], d["buyVolume"]
                fa = num(ba, FOREIGN)
                ia = num(ba, INST)
                fv = num(bv, FOREIGN)
                iv = num(bv, INST)
                if fa + ia <= 0 or fv + iv <= 0:
                    continue
                rows.append((d["ticker"], d["date"], fa, ia, fv, iv))
        df = pd.DataFrame(rows, columns=["ticker", "date", "fBuyAmt", "iBuyAmt", "fBuyVol", "iBuyVol"])
        df.to_parquet(out_path, index=False)
        print(f"{year}: rows={len(df)} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
