#!/usr/bin/env python3
"""KRX 주식선물 일별(유가 eqsfu_stk · 코스닥 eqkfu_ksq) — 근월 선물(F, 스프레드 SP 제외)만, 기초자산 종목코드를 붙여 저장.

    python research/strategy-lab/collect_stock_futures_krx.py 2023-01-01 2026-10-08
저장(gitignore): data/stock-futures/YYYY.parquet. 이미 받은 날은 건너뛴다(재개 가능). KRX Open API(무료·한도 없음, KRX_OPENAPI_KEY).
기초자산 코드 = 같은 날 KRX 일별(data/krx-daily-ext)에서 종가 == SPOT_PRC 이고 이름 앞부분이 같은 종목. 못 찾으면 버린다(기록).
근월 = 기초자산마다 그날 거래량 최대인 F 종목(만기 직전 교체 구간도 거래량으로 고른다).
"""
from __future__ import annotations

import glob
import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect_krx_daily_2010 as base  # noqa: E402

OUT = HERE / "data" / "stock-futures"
PATHS = {"KOSPI": "drv/eqsfu_stk_bydd_trd", "KOSDAQ": "drv/eqkfu_ksq_bydd_trd"}
NUM = ["TDD_CLSPRC", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "SPOT_PRC", "SETL_PRC", "ACC_TRDVOL", "ACC_TRDVAL", "ACC_OPNINT_QTY"]


def fetch(k, path, d):
    for a in range(3):
        try:
            req = urllib.request.Request(f"https://data-dbg.krx.co.kr/svc/apis/{path}?basDd={d}", headers={"AUTH_KEY": k, "User-Agent": "Mozilla/5.0 stock-research"})
            return json.load(urllib.request.urlopen(req, timeout=60)).get("OutBlock_1", [])
        except Exception:
            if a == 2:
                raise
            time.sleep(3)


def num(s):
    return pd.to_numeric(s.astype(str).str.replace(",", ""), errors="coerce")


def main():
    a, b = sys.argv[1].replace("-", ""), sys.argv[2].replace("-", "")
    k = base.key()
    fs = sorted(glob.glob(str(HERE / "data" / "krx-daily-ext" / "20*.parquet")))
    daily = pd.concat([pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "ISU_NM", "TDD_CLSPRC"]) for f in fs if a[:4] <= Path(f).stem[:4] <= b[:4]], ignore_index=True)
    days = sorted(d for d in daily.BAS_DD.unique() if a <= d <= b)
    OUT.mkdir(parents=True, exist_ok=True)
    have = set()
    for p in OUT.glob("*.parquet"):
        have |= set(pd.read_parquet(p, columns=["BAS_DD"]).BAS_DD)
    todo = [d for d in days if d not in have]
    print(f"거래일 {len(days)} · 받을 날 {len(todo)}", flush=True)
    buf, miss = [], 0
    for i, d in enumerate(todo, 1):
        dd = daily[daily.BAS_DD == d]
        for mkt, path in PATHS.items():
            rows = fetch(k, path, d)
            if not rows:
                continue
            f = pd.DataFrame(rows)
            f = f[f.ISU_NM.str.contains(r"\sF\s", regex=True)].copy()
            for c in NUM:
                f[c] = num(f[c])
            f["under"] = f.ISU_NM.str.split(r"\s+F\s", regex=True).str[0].str.strip()
            f = f.sort_values("ACC_TRDVOL", ascending=False).drop_duplicates("under")
            m = f.merge(dd, left_on="SPOT_PRC", right_on="TDD_CLSPRC", how="left", suffixes=("", "_stk"))
            m = m[m.apply(lambda r: isinstance(r.ISU_NM_stk, str) and r.ISU_NM_stk.replace(" ", "").startswith(r.under.replace(" ", "")[:4]), axis=1)]
            m = m.drop_duplicates("under")
            miss += len(f) - len(m)
            m = m.rename(columns={"ISU_CD_stk": "ticker"})[["BAS_DD", "ticker", "ISU_CD", "ISU_NM", "under"] + NUM]
            m["market"] = mkt
            buf.append(m)
        if i % 50 == 0 or i == len(todo):
            df = pd.concat(buf, ignore_index=True)
            for y, g in df.groupby(df.BAS_DD.str[:4]):
                p = OUT / f"{y}.parquet"
                old = pd.read_parquet(p) if p.exists() else pd.DataFrame()
                pd.concat([old, g], ignore_index=True).drop_duplicates(["BAS_DD", "ISU_CD"]).to_parquet(p)
            buf = []
            print(f"  {i}/{len(todo)} · 기초자산 매칭 실패 누적 {miss}", flush=True)
        time.sleep(0.2)
    print("완료")


if __name__ == "__main__":
    main()
