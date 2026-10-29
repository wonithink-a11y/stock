#!/usr/bin/env python3
"""바이낸스 신규 상장 BL7 — 업비트 원화 가격 확인. 사전등록 findings/binance-listing-upbit-preregistration-2026-10.md.

    python research/strategy-lab/futures/binance_listing_upbit.py             # 판정(새 수집 없음)
    python research/strategy-lab/futures/binance_listing_upbit.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

UP = HERE.parent / "data" / "crypto" / "upbit_day"
D = pd.Timedelta(days=1)


def rel(p: pd.Series, b: pd.Series, L: pd.Timestamp, h: int = 7) -> float:
    t0, t1 = L + D, L + (1 + h) * D
    v = [p.get(t0, np.nan), p.get(t1, np.nan), b.get(t0, np.nan), b.get(t1, np.nan)]
    return ((v[1] / v[0] - 1) - (v[3] / v[2] - 1)) * 1e4 if all(np.isfinite(v)) and t1 < bl.END else np.nan


def st(x: pd.Series) -> dict:
    return {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} if len(x) else {"n": 0}


def main():
    months = json.loads((bl.DATA / "months.json").read_text(encoding="utf-8"))
    ub = rb._read(UP / "KRW-BTC.parquet")["open"]
    btc = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    btc = btc[btc.index.hour == 0]
    rows = []
    for e in bl.events_table(months):
        f, fu = bl.DATA / f"{e['sym']}.parquet", UP / f"KRW-{e['base']}.parquet"
        if not (f.exists() and fu.exists()):
            continue
        p = rb._read(f)["open"].dropna()
        u = rb._read(fu)
        if not len(p) or not len(u):
            continue
        L = p.index[0]
        ru, rbn = rel(u["open"], ub, L), rel(p, btc, L)
        if np.isfinite(ru):
            rows.append({"L": L, "up": ru, "bn": rbn, "upbit_first": bool(u.index[0] < L)})
    df = pd.DataFrame(rows)
    day = df.groupby("L")[["up", "bn"]].mean()
    s = day["up"]
    o = s[s.index.year >= 2023]
    if len(s) < 20:
        v = "판정불가"
    elif s.mean() >= 0:
        v = "NOT"
    elif tstat(s.to_numpy()) <= -2 and o.mean() < 0:
        v = "CONSISTENT"
    else:
        v = "WEAK"
    out = {"verdict": v, "upbit_all": st(s), "upbit_2023on": st(o), "binance_same_subset": st(day["bn"].dropna()),
           "by_split": {k: st(x) for k, x in s.groupby(s.index.map(cp.split))},
           "coins": int(len(df)), "coin_lose%": round(float((df["up"] < 0).mean() * 100), 1),
           "upbit_listed_before_binance%": round(float(df["upbit_first"].mean() * 100), 1),
           "by_year": {int(y): int(n) for y, n in s.groupby(s.index.year).size().items()}}
    (HERE / "binance-listing-upbit.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    idx = pd.date_range("2024-01-01", periods=20, freq="D", tz="UTC")
    p = pd.Series(100.0, index=idx); p[idx[9]] = 80.0
    b = pd.Series(10.0, index=idx); b[idx[9]] = 11.0
    assert abs(rel(p, b, idx[1]) - (-0.2 - 0.1) * 1e4) < 1e-6
    print("selftest 1/1 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
