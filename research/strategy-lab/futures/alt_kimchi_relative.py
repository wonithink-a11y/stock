#!/usr/bin/env python3
"""알트 상대 김치 프리미엄 → 업비트 알트 1·7일. 사전등록 findings/alt-kimchi-relative-preregistration-2026-10.md.

    python research/strategy-lab/futures/alt_kimchi_relative.py             # 판정(새 수집 없음)
    python research/strategy-lab/futures/alt_kimchi_relative.py --selftest
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

SEED = 20261104
UP = HERE.parent / "data" / "crypto" / "upbit_day"
COINS = ["AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "BCH", "DOGE", "DOT", "ETH", "FIL", "INJ", "LINK", "NEAR", "OP", "SOL", "SUI", "UNI", "WLD"]
WIN, MINP, ZTH = 30, 20, 2.0
CELLS = {"K1": 1, "K7": 7}
D = pd.Timedelta(days=1)
END = pd.Timestamp("2026-10-01", tz="UTC")


def bn_close_daily(h: pd.DataFrame) -> pd.Series:
    c = h["close"]
    c = c[c.index.hour == 23]
    c.index = c.index.normalize()
    return c


def rel_premium(u: pd.DataFrame, ub: pd.DataFrame, b: pd.DataFrame, bb: pd.DataFrame) -> pd.Series:
    idx = pd.date_range(pd.Timestamp("2017-09-01", tz="UTC"), END - D, freq="D")
    uc, ubc = u["close"].reindex(idx), ub["close"].reindex(idx)
    bc, bbc = bn_close_daily(b).reindex(idx), bn_close_daily(bb).reindex(idx)
    return np.log(uc / ubc) - np.log(bc / bbc)


def zscore(x: pd.Series) -> pd.Series:
    past = x.shift(1).rolling(WIN, min_periods=MINP)
    return (x - past.mean()) / past.std()


def coin_events(z: pd.Series, opn: pd.Series, h: int, side: int = 0) -> pd.Series:
    """사건일 d → s × (O(d+1+h)/O(d+1) − 1) bp, s = −sign(z). side 로 갈래만."""
    out, free = {}, None
    for d, v in z[z.abs() >= ZTH].items():
        s = -np.sign(v)
        if side and s != side:
            continue
        t0 = d + D
        if free is not None and t0 < free:
            continue
        if t0 + h * D > END:
            break
        p0, p1 = opn.get(t0, np.nan), opn.get(t0 + h * D, np.nan)
        if not (np.isfinite(p0) and np.isfinite(p1)):
            continue
        out[d] = s * (p1 / p0 - 1) * 1e4
        free = t0 + h * D
    return pd.Series(out, dtype=float)


def by_day(per_coin: dict[str, pd.Series]) -> pd.Series:
    allv = pd.concat([s.rename(c) for c, s in per_coin.items() if len(s)], axis=1, sort=True)
    return allv.mean(axis=1, skipna=True).dropna()


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def main():
    ub = rb._read(UP / "KRW-BTC.parquet")
    bb = rb._read(cp.DATA / "bn_btc.parquet")
    z, U, B = {}, {}, {}
    for c in COINS:
        U[c] = rb._read(UP / f"KRW-{c}.parquet")
        B[c] = rb._read(cp.DATA / "alts" / f"{c}_bn.parquet")
        z[c] = zscore(rel_premium(U[c], ub, B[c], bb))
    out, series = {"coins": COINS, "cells": {}}, {}
    for k, h in CELLS.items():
        series[k] = by_day({c: coin_events(z[c], U[c]["open"], h) for c in COINS})
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out["bar"] = round(bar, 2)
    for k, h in CELLS.items():
        r = cp.judge(series[k], bar)
        r["legs"] = {"상대 고평가(숏)": brief(by_day({c: coin_events(z[c], U[c]["open"], h, -1) for c in COINS})),
                     "상대 저평가(롱, 업비트 가능)": brief(by_day({c: coin_events(z[c], U[c]["open"], h, 1) for c in COINS}))}
        pc = {c: coin_events(z[c], U[c]["open"], h) for c in COINS}
        r["events_total"] = int(sum(len(s) for s in pc.values()))
        r["event_level"] = brief(pd.concat(pc.values()).sort_index())
        out["cells"][k] = r
    rec = {}
    ubo = ub["open"]
    bo = {c: B[c]["open"][B[c]["open"].index.hour == 0] for c in COINS}
    for k, h in CELLS.items():
        rel = {}
        for c in COINS:
            e = coin_events(z[c], U[c]["open"], h)
            sg = -np.sign(z[c].reindex(e.index))
            btc = np.array([(ubo.get(d + D + h * D, np.nan) / ubo.get(d + D, np.nan) - 1) * 1e4 for d in e.index])
            rel[c] = e - sg.to_numpy() * btc
        rec[f"{k}_relative_to_upbit_btc"] = brief(by_day(rel))
        rec[f"{k}_binance_alt"] = brief(by_day({c: coin_events(z[c], bo[c], h) for c in COINS}))
    rec["events_by_coin_K1"] = {c: int(len(coin_events(z[c], U[c]["open"], 1))) for c in COINS}
    out["record"] = rec
    (HERE / "alt-kimchi-relative.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    idx = pd.date_range("2020-01-01", periods=80, freq="D", tz="UTC")
    u = pd.DataFrame({"open": 100.0, "close": 100.0}, index=idx)
    ub = pd.DataFrame({"open": 1000.0, "close": 1000.0}, index=idx)
    hrs = pd.date_range("2020-01-01", periods=80 * 24, freq="h", tz="UTC")
    b = pd.DataFrame({"open": 10.0, "close": 10.0}, index=hrs)
    bb = pd.DataFrame({"open": 100.0, "close": 100.0}, index=hrs)
    u.loc[idx[50], "close"] = 110.0                                    # 50일째 업비트만 10% 비쌈
    rk = rel_premium(u, ub, b, bb)
    assert abs(rk[idx[50]] - np.log(1.1)) < 1e-12 and abs(rk[idx[49]]) < 1e-12; ok += 1
    rng = np.random.default_rng(0)
    rk = rk + pd.Series(rng.normal(0, 1e-4, len(rk)), index=rk.index)
    z = zscore(rk)
    assert z[idx[50]] > ZTH; ok += 1
    u.loc[idx[52], "open"] = 90.0                                      # 진입 51, 1일 뒤 52 −10% → 숏 +1000bp
    e = coin_events(z.where(z.index == idx[50], 0.0), u["open"], 1)
    assert abs(e[idx[50]] - 1000.0) < 1e-6; ok += 1
    s1 = pd.Series({idx[3]: 10.0, idx[5]: 30.0}); s2 = pd.Series({idx[3]: 20.0})
    d = by_day({"A": s1, "B": s2})
    assert d[idx[3]] == 15.0 and d[idx[5]] == 30.0; ok += 1           # 같은 날은 평균 하나
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
