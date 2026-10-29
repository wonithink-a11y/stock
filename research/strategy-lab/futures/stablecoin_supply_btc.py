#!/usr/bin/env python3
"""스테이블코인 발행량 → BTC 1·7일. 사전등록 findings/stablecoin-supply-btc-preregistration-2026-10.md.

    python research/strategy-lab/futures/stablecoin_supply_btc.py --collect   # DefiLlama 공개 API → data/crypto/cbprem/stablecoin_*.json
    python research/strategy-lab/futures/stablecoin_supply_btc.py             # 판정
    python research/strategy-lab/futures/stablecoin_supply_btc.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402  판정·구간 그대로(20401a4)
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261102
D = pd.Timedelta(days=1)
GROW, WIN, MINP, ZTH = 7, 180, 90, 2.0
CELLS = {"S1": 1, "S7": 7}
SRC = {"all": "https://stablecoins.llama.fi/stablecoincharts/all",
       "usdt": "https://stablecoins.llama.fi/stablecoin/1", "usdc": "https://stablecoins.llama.fi/stablecoin/2"}
OOS_END = pd.Timestamp("2026-10-01", tz="UTC")


def collect():
    import requests
    for k, u in SRC.items():
        r = requests.get(u, timeout=60)
        r.raise_for_status()
        (cp.DATA / f"stablecoin_{k}.json").write_text(r.text, encoding="utf-8")
    print({k: len(load_supply(k)) for k in SRC})


def load_supply(kind: str) -> pd.Series:
    j = json.loads((cp.DATA / f"stablecoin_{kind}.json").read_text(encoding="utf-8"))
    if kind == "all":
        rows = [(int(x["date"]), (x.get("totalCirculatingUSD") or {}).get("peggedUSD")) for x in j]
    else:
        rows = [(int(x["date"]), (x.get("circulating") or {}).get("peggedUSD")) for x in j["tokens"]]
    s = pd.Series({pd.Timestamp(t, unit="s", tz="UTC").normalize(): v for t, v in rows if v}, dtype=float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(pd.date_range(s.index[0], s.index[-1], freq="D"))   # 빠진 날은 결측(채우지 않는다)


def zscore(S: pd.Series) -> pd.Series:
    g = np.log(S / S.shift(GROW))
    past = g.shift(1).rolling(WIN, min_periods=MINP)
    return (g - past.mean()) / past.std()


def events(z: pd.Series, open_d: pd.Series, h: int) -> pd.Series:
    """사건일 d 인덱스 → s × 수익 bp. 진입 d+1 00:00 UTC, 보유 중 새 사건 무시."""
    out, free = {}, None
    for d, v in z[z.abs() >= ZTH].items():
        t0 = d + D
        if free is not None and t0 < free:
            continue
        p0, p1 = open_d.get(t0, np.nan), open_d.get(t0 + h * D, np.nan)
        if not (np.isfinite(p0) and np.isfinite(p1)):
            continue
        out[d] = np.sign(v) * (p1 / p0 - 1) * 1e4
        free = t0 + h * D
    return pd.Series(out, dtype=float)


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def main():
    bn = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    open_d = bn[bn.index.hour == 0]
    S = load_supply("all")
    z = zscore(S)
    z = z[z.index < OOS_END]
    series = {k: events(z, open_d, h) for k, h in CELLS.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "supply_first": str(S.first_valid_index().date()), "z_days": int(z.notna().sum()), "cells": {}}
    for k, s in series.items():
        r = cp.judge(s, bar)
        sg = z.reindex(s.index)
        r["legs"] = {"growth(z≥2)": brief(s[(sg > 0).to_numpy()]), "contraction(z≤−2)": brief(s[(sg < 0).to_numpy()])}
        out["cells"][k] = r
    rec = {}
    for kind in ("usdt", "usdc"):
        zk = zscore(load_supply(kind))
        zk = zk[zk.index < OOS_END]
        rec[kind] = {k: brief(events(zk, open_d, h)) for k, h in CELLS.items()}
    g = np.log(S / S.shift(GROW))
    wk = g.dropna().iloc[::7]
    fwd = pd.Series([(open_d.get(d + 8 * D, np.nan) / open_d.get(d + D, np.nan) - 1) for d in wk.index], index=wk.index)
    both = pd.concat([wk, fwd], axis=1).dropna()
    both = both[both.index < OOS_END]
    rec["weekly_spearman_g_vs_next7d"] = {"all": round(float(both.iloc[:, 0].corr(both.iloc[:, 1], method="spearman")), 3), "weeks": int(len(both)),
                                         "by_year": {int(y): round(float(x.iloc[:, 0].corr(x.iloc[:, 1], method="spearman")), 3)
                                                     for y, x in both.groupby(both.index.year) if len(x) > 10}}
    cb, bnc = (rb._read(cp.DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc"))
    zc = cp.zscore(cp.premium(cb, bnc))
    zc7 = zc.groupby(zc.index.normalize()).mean().rolling(7).mean()
    jj = pd.concat([g, zc7], axis=1).dropna()
    rec["corr_g_vs_coinbase_z_7d"] = round(float(jj.iloc[:, 0].corr(jj.iloc[:, 1])), 3)
    ev7 = series["S7"]
    rec["events_by_year_S7"] = {int(y): int(len(x)) for y, x in ev7.groupby(ev7.index.year)}
    out["record"] = rec
    (HERE / "stablecoin-supply-btc.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    days = pd.date_range("2020-01-01", periods=600, freq="D", tz="UTC")
    rng = np.random.default_rng(4)
    S = pd.Series(1e9 * np.exp(np.cumsum(rng.normal(0.002, 0.002, len(days)))), index=days)
    S.iloc[400:] *= 1.08                                     # 400일째 발행 급증 → g(400..406) 큼
    z = zscore(S)
    assert z.iloc[400] > ZTH
    z2 = zscore(S.where(S.index <= days[420], S * 3))           # 미래를 바꿔도 과거 z 는 그대로
    assert np.allclose(z.iloc[:421].dropna(), z2.iloc[:421].dropna())
    op = pd.Series(100.0, index=pd.date_range("2020-01-01", periods=len(days) + 29, freq="D", tz="UTC"))
    op[days[401] + 7 * D] = 110.0
    e = events(z, op, 7)
    assert days[400] in e.index and abs(e[days[400]] - 1000.0) < 1e-6   # 진입 d+1, 7일 뒤 +10%
    assert ((e.index[1:] - e.index[:-1]) >= 7 * D).all()                # 보유 중 새 사건 없음
    print("selftest 4/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
