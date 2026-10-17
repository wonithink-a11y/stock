#!/usr/bin/env python3
"""크립토 청산 연쇄 뒤 반등 — 사전등록 findings/crypto-liquidation-rebound-preregistration-2026-10.md.

가격 적재·집계·판정은 crypto_short_horizon / crypto_positioning_study 를 그대로 쓴다.
    python research/strategy-lab/futures/crypto_liquidation_rebound.py
    python research/strategy-lab/futures/crypto_liquidation_rebound.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from crypto_short_horizon import aggregate, load, seq, split  # noqa: E402
from crypto_positioning_study import MET, judge  # noqa: E402
from short_horizon_study import null_bar, tstat  # noqa: E402
import crypto_positioning_study as cps  # noqa: E402

SEED = 20261017
cps.SEED = SEED          # judge 의 부트스트랩 시드
W, MINP = 720, 360


def prev_pct(s: pd.Series) -> pd.Series:
    """직전 W 개(현재 제외) 중 현재보다 작은 비율."""
    return s.rolling(W + 1, min_periods=MINP + 1).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)


def events(p: pd.Series, oi: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """(사건, 대조 L0) 불리언 — p·oi 는 같은 1시간 인덱스."""
    r1 = p / p.shift(1) - 1
    s1 = r1.shift(1).rolling(W, min_periods=MINP).std()
    q = prev_pct(oi / oi.shift(1) - 1)
    crash = (r1 < -3 * s1).to_numpy()
    qv = q.to_numpy()
    return crash & (qv <= 0.05), crash & (qv > 0.05)


def oi_at(sym: str, idx: pd.DatetimeIndex) -> pd.Series | None:
    f = MET / f"{sym}.parquet"
    if not f.exists():
        return None
    m = pd.read_parquet(f, columns=["create_time", "sum_open_interest"])
    m["t"] = pd.to_datetime(m["create_time"], utc=True)
    m["oi"] = pd.to_numeric(m["sum_open_interest"], errors="coerce")
    m = m.drop_duplicates("t").sort_values("t")[["t", "oi"]]
    j = pd.merge_asof(pd.DataFrame({"t": idx}), m, on="t", direction="backward", tolerance=pd.Timedelta("15min"))
    return j.set_index("t")["oi"]


def period(t) -> str:
    return "~2023" if t.year <= 2023 else ("2024" if t.year == 2024 else "2025~")


def main():
    coins = load()
    ev = {"L1": [], "L2": [], "L0_4h": [], "L0_24h": []}
    per_coin, start = {}, {}
    for sym, (d, _) in coins.items():
        p = d["mark_open"]
        oi = oi_at(sym, p.index)
        if oi is None or oi.notna().sum() < W:
            continue
        first = oi.first_valid_index()
        start[sym] = str(first)
        p, oi = p[p.index >= first], oi[oi.index >= first]
        e, c = events(p, oi)
        f = pd.DataFrame({"p": p})
        one = np.ones(len(f))
        ev["L1"] += seq(f, e, one, 4)
        ev["L2"] += seq(f, e, one, 24)
        ev["L0_4h"] += seq(f, c, one, 4)
        ev["L0_24h"] += seq(f, c, one, 24)
        per_coin[sym] = int(e.sum())
    series = {k: aggregate(v) for k, v in ev.items()}
    rng = np.random.default_rng(SEED)
    bar = null_bar([series[k][series[k].index.map(split) == "TRAIN"].to_numpy() for k in ("L1", "L2")], rng)
    out = {"bar": round(bar, 2), "coins": len(start), "metrics_start": start, "events_per_coin": per_coin, "cells": {}}
    for k in ("L1", "L2"):
        s = series[k]
        r = judge(s, bar)
        r["periods_bp"] = {g: {"n": int(len(v)), "bp": round(float(v.mean()), 1), "t": round(tstat(v.to_numpy()), 2)}
                           for g, v in s.groupby(s.index.map(period))}
        r["yearly_bp"] = {int(y): round(float(v), 1) for y, v in s.groupby(s.index.year).mean().items()}
        out["cells"][k] = r
    rec = {}
    for k in ("L0_4h", "L0_24h"):
        s = series[k]
        rec[k] = {g: {"n": int(len(v)), "bp": round(float(v.mean()), 1), "t": round(tstat(v.to_numpy()), 2)}
                  for g, v in s.groupby(s.index.map(split))}
    rec["raw_trades"] = {k: len(v) for k, v in ev.items()}
    bb = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        d, _ = coins[sym]
        p = d["mark_open"]
        oi = oi_at(sym, p.index)
        first = oi.first_valid_index()
        p, oi = p[p.index >= first], oi[oi.index >= first]
        e, _ = events(p, oi)
        f = pd.DataFrame({"p": p})
        for h in (4, 24):
            v = np.array([x[1] for x in seq(f, e, np.ones(len(f)), h)])
            bb[f"{sym}_{h}h"] = {"n": int(len(v)), "bp": round(float(v.mean()), 1) if len(v) else None}
    rec["btc_eth"] = bb
    out["record"] = rec
    (HERE / "crypto-liquidation-rebound.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("bar", out["bar"], "coins", out["coins"])
    for c, r in out["cells"].items():
        print(c, r["verdict"], "s", r["sign"], "tTR", r["t_train"], {k: r[k] for k in ("TRAIN", "VALID", "TEST")},
              "oos", r["oos_gross_bp"], r["oos_gross_ci95"], "net", r["net_oos"], r["net_oos_stress"], "tnet", r["t_net_oos"])
        print("   periods", r["periods_bp"], "\n   yearly", r["yearly_bp"])
    print("record", json.dumps(rec, ensure_ascii=False))


def selftest():
    idx = pd.date_range("2021-01-01", periods=24 * 200, freq="h", tz="UTC")
    rng = np.random.default_rng(3)
    p = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.004, len(idx)))), index=idx)
    oi = pd.Series(1e6 * np.exp(np.cumsum(rng.normal(0, 0.002, len(idx)))), index=idx)
    e, c = events(p, oi)
    assert e[:MINP + 1].sum() == 0, "창이 차기 전 사건"
    # 급락 + OI 급감을 심으면 사건, OI 그대로면 대조
    q, o = p.to_numpy().copy(), oi.to_numpy().copy()
    i, j = 3000, 4000
    q[i:] *= 0.95
    o[i:] *= 0.9
    q[j:] *= 0.95
    e2, c2 = events(pd.Series(q, index=idx), pd.Series(o, index=idx))
    assert e2[i] and not c2[i], "사건 미검출"
    assert c2[j] and not e2[j], "대조 미검출"
    assert np.isnan(prev_pct(pd.Series(np.arange(10.0))).iloc[5])
    print("selftest 3/3 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
