#!/usr/bin/env python3
"""BTC–나스닥 괴리 되돌림 → BTC 1·5거래일. 사전등록 findings/btc-nasdaq-divergence-preregistration-2026-10.md.

    python research/strategy-lab/futures/btc_nasdaq_divergence.py --collect   # Yahoo ^NDX 일봉 → data/crypto/xasset/
    python research/strategy-lab/futures/btc_nasdaq_divergence.py             # 판정
    python research/strategy-lab/futures/btc_nasdaq_divergence.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261111
DATA = HERE.parent / "data" / "crypto" / "xasset"
NY = "America/New_York"
W, BW, BMIN, SW, SMIN, ZTH = 5, 120, 100, 250, 150, 2.0
CELLS = {"N5": 5, "N1": 1}
END = pd.Timestamp("2026-10-01", tz="UTC")


def collect():
    import requests
    DATA.mkdir(parents=True, exist_ok=True)
    r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%5ENDX", params={"period1": 1483228800, "period2": 1793318400, "interval": "1d"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    (DATA / "ndx.json").write_text(r.text, encoding="utf-8")
    n = load_ndx()
    print(len(n), n.index[0].date(), n.index[-1].date())


def load_ndx() -> pd.Series:
    d = json.loads((DATA / "ndx.json").read_text(encoding="utf-8"))["chart"]["result"][0]
    days = pd.to_datetime(d["timestamp"], unit="s", utc=True).tz_convert(NY).normalize().tz_localize(None)
    s = pd.Series(d["indicators"]["quote"][0]["close"], index=days, dtype=float).dropna()
    return s[~s.index.duplicated(keep="last")]


def close_utc(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return (days + pd.Timedelta(hours=16)).tz_localize(NY).tz_convert("UTC")


def frame(ndx: pd.Series, o: pd.Series) -> pd.DataFrame:
    t_utc = close_utc(ndx.index)
    btc = pd.Series(o.reindex(t_utc).to_numpy(), index=ndx.index)
    f = pd.DataFrame({"ndx": ndx, "btc": btc, "t_utc": t_utc}).dropna()
    f["a"], f["n"] = f["btc"].pct_change(), f["ndx"].pct_change()
    f["A"] = f["btc"] / f["btc"].shift(W) - 1
    f["N"] = f["ndx"] / f["ndx"].shift(W) - 1
    a, n = f["a"].shift(W), f["n"].shift(W)                  # 현재 5일 창 제외
    cov = (a * n).rolling(BW, min_periods=BMIN).mean() - a.rolling(BW, min_periods=BMIN).mean() * n.rolling(BW, min_periods=BMIN).mean()
    var = n.rolling(BW, min_periods=BMIN).var(ddof=0)
    f["beta"] = cov / var
    f["e"] = f["A"] - f["beta"] * f["N"]
    f["e0"] = f["A"]
    for col, zc in (("e", "z"), ("e0", "z0")):
        f[zc] = f[col] / f[col].shift(W).rolling(SW, min_periods=SMIN).std()
    return f


def events(f: pd.DataFrame, h: int, zcol: str = "z", side: int = 0) -> pd.Series:
    out, free = {}, -1
    pos = {d: i for i, d in enumerate(f.index)}
    for d, z in f[zcol][f[zcol].abs() >= ZTH].items():
        s = -np.sign(z)
        if side and s != side:
            continue
        i = pos[d]
        if i < free or i + h >= len(f):
            continue
        if f["t_utc"].iloc[i + h] >= END:
            break
        out[pd.Timestamp(d, tz="UTC")] = s * (f["btc"].iloc[i + h] / f["btc"].iloc[i] - 1) * 1e4
        free = i + h
    return pd.Series(out, dtype=float)


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def main():
    o = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    f = frame(load_ndx(), o)
    series = {k: events(f, h) for k, h in CELLS.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "days": int(f["z"].notna().sum()), "cells": {}}
    for k, s in series.items():
        r = cp.judge(s, bar)
        r["legs"] = {"BTC 뒤처짐(롱)": brief(events(f, CELLS[k], side=1)), "BTC 앞섬(숏)": brief(events(f, CELLS[k], side=-1))}
        out["cells"][k] = r
    g = f.dropna(subset=["a", "n"])
    out["record"] = {"beta_mean_by_year": {int(y): round(float(x["beta"].mean()), 2) for y, x in f.groupby(f.index.year) if x["beta"].notna().any()},
                     "corr_by_year": {int(y): round(float(x["a"].corr(x["n"])), 2) for y, x in g.groupby(g.index.year)},
                     "beta0": {k: brief(events(f, h, "z0")) for k, h in CELLS.items()}}
    (HERE / "btc-nasdaq-divergence.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    u = close_utc(pd.DatetimeIndex(["2024-07-12", "2024-01-12"]))
    assert str(u[0]) == "2024-07-12 20:00:00+00:00" and str(u[1]) == "2024-01-12 21:00:00+00:00"; ok += 1
    days = pd.bdate_range("2020-01-01", periods=400)
    rng = np.random.default_rng(2)
    nd = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, len(days)))), index=days)
    hrs = pd.date_range(close_utc(days[:1])[0] - pd.Timedelta(days=2), close_utc(days[-1:])[0] + pd.Timedelta(days=2), freq="h")
    o = pd.Series(np.nan, index=hrs)
    b = 100 * np.exp(np.cumsum(2 * np.log(nd / nd.shift(1)).fillna(0).to_numpy()))   # BTC = 2 × NDX 일수익(로그)
    o[close_utc(days)] = b
    o = o.ffill()
    f = frame(nd, o)
    assert abs(f["beta"].dropna().iloc[-1] - 2.0) < 0.1; ok += 1                     # β ≈ 2
    assert f["e"].dropna().abs().max() < 0.01; ok += 1                               # 설명되므로 잔차 ≈ 0
    print(f"selftest {ok}/3 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
