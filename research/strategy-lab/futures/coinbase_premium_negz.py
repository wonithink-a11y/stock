#!/usr/bin/env python3
"""코인베이스 프리미엄 마이너스 z 문턱·보유 → BTC. 사전등록 findings/coinbase-premium-negz-preregistration-2026-10.md(8f869c7).

    python research/strategy-lab/futures/coinbase_premium_negz.py             # 판정 → futures/coinbase-premium-negz.json
    python research/strategy-lab/futures/coinbase_premium_negz.py --selftest

자료·P·z·판정 사다리는 coinbase_premium.py(20401a4)를 고치지 않고 불러 쓴다. 새 수집 없음(data/crypto/cbprem/).
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
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261030
KS = [-1.0, -1.5, -2.5, -3.0, -4.0]
HS = [24, 72]
REC_KS = [-2.0, -5.0, -6.0]


def neg_events(z: pd.Series, bo: pd.Series, k: float, h: int) -> pd.Series:
    """z ≤ k 첫 시각 T → (O(T+h)/O(T) − 1) bp, 롱 기준. 사건 뒤 h 시간 새 사건 안 받음."""
    out, free = {}, None
    for T in z.index[(z <= k).to_numpy()]:
        if free is not None and T < free:
            continue
        p0, p1 = bo.get(T, np.nan), bo.get(T + h * cp.H, np.nan)
        if not (np.isfinite(p0) and np.isfinite(p1)):
            continue
        out[T] = (p1 / p0 - 1) * 1e4
        free = T + h * cp.H
    return pd.Series(out, dtype=float)


def drift(bo: pd.Series, h: int) -> dict:
    r = ((bo.shift(-h) / bo - 1) * 1e4).dropna()
    r = r[(r.index >= cp.START) & (r.index < cp.END)]
    return {k: round(float(x.mean()), 1) for k, x in r.groupby(r.index.map(cp.split))}


def main():
    cb, bn = (pd.read_parquet(cp.DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc"))
    for d in (cb, bn):
        d.index = pd.to_datetime(d.index, utc=True)
    bo = bn["open"]
    z = cp.zscore(cp.premium(cb, bn)).dropna()
    cells = {f"k{k:g}_h{h}": neg_events(z, bo, k, h) for k in KS for h in HS}
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in cells.values()], np.random.default_rng(SEED))
    out = {"bar": round(bar, 2), "z_hours": int(len(z)), "cells": {k: cp.judge(s, bar) for k, s in cells.items()},
           "drift_bp": {f"h{h}": drift(bo, h) for h in HS}}
    rec = {f"k{k:g}_h{h}": cp.brief(neg_events(z, bo, k, h)) for k in REC_KS for h in HS}
    e2 = neg_events(z, bo, -2.0, 24)
    deep = pd.Series({T: bool(z[T:T + 23 * cp.H].min() <= -3) for T in e2.index})
    rec["deepen_-2_to_-3_within24h"] = {"deeper": cp.brief(e2[deep]), "not": cp.brief(e2[~deep])}
    e4 = neg_events(z, bo, -4.0, 24)
    rec["deep_list_k-4_h24"] = [{"T": str(T), "z": round(float(z[T]), 2), "r24_bp": round(float(v), 1)} for T, v in e4.items()]
    out["record"] = rec
    (HERE / "coinbase-premium-negz.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"bar": out["bar"], **{k: {kk: v[kk] for kk in ("verdict", "sign", "t_train")} for k, v in out["cells"].items()}}, ensure_ascii=False))


def selftest():
    idx = pd.date_range("2020-01-01", periods=200, freq="h", tz="UTC")
    z = pd.Series(0.0, index=idx)
    z.iloc[[10, 12, 40, 41]] = [-3.0, -5.0, -1.2, -2.0]
    bo = pd.Series(np.arange(200, dtype=float) + 100, index=idx)
    e = neg_events(z, bo, -1.0, 24)
    assert list(e.index) == [idx[10], idx[40]]                       # 12 는 차단 중, 41 은 40 차단 중
    assert abs(e.iloc[0] - ((134 / 110) - 1) * 1e4) < 1e-9           # 시가 T → T+24
    assert list(neg_events(z, bo, -4.0, 24).index) == [idx[12]]
    assert len(neg_events(z, bo, -1.0, 500)) == 0                    # T+h 가격 없으면 버림
    print("selftest 4/4 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
