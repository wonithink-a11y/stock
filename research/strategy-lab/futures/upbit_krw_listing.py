#!/usr/bin/env python3
"""업비트 원화 신규 상장 뒤 되돌림 — 사전등록 findings/upbit-krw-listing-preregistration-2026-10.md.

    python research/strategy-lab/futures/upbit_krw_listing.py --selftest
    python research/strategy-lab/futures/upbit_krw_listing.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import null_bar, tstat  # noqa: E402

D = HERE.parent / "data" / "crypto" / "upbit-listings"
SEED = 20261017
COST, STRESS = 10.0, 20.0
H = {"U1": 7, "U2": 30}


def split(y: int) -> str:
    return "TRAIN" if y <= 2021 else ("VALID" if y <= 2023 else "TEST")


def period(y: int) -> str:
    return "~2023" if y <= 2023 else ("2024" if y == 2024 else "2025~")


def ret(s: pd.Series, a: pd.Timestamp, b: pd.Timestamp) -> float:
    try:
        return float(s.loc[b] / s.loc[a] - 1)
    except KeyError:
        return np.nan


def event(d0, cb: pd.Series, bb: pd.Series, up: pd.Series, upbtc: pd.Series) -> dict | None:
    """cb·bb = 바이낸스 코인·BTC 종가(날짜 인덱스), up·upbtc = 업비트 원화 종가. 표본 조건 불통과면 None."""
    day = pd.Timedelta(days=1)
    if cb.index.min() > d0 - day:
        return "not_prior"
    w = pd.date_range(d0 + day, d0 + 5 * day)
    r = (up.reindex(w) / cb.reindex(w)).median() / (upbtc.reindex(w) / bb.reindex(w)).median()
    if not (0.7 <= r <= 1.4):
        return "price_mismatch"
    out = {}
    for k, h in H.items():
        c, b = ret(cb, d0, d0 + h * day), ret(bb, d0, d0 + h * day)
        out[k] = (-c * 1e4, -(c - b) * 1e4) if np.isfinite(c) and np.isfinite(b) else None
    for k, (a, z) in {"pump_d0": (-1, 0), "pre_7_1": (-7, -1)}.items():
        c, b = ret(cb, d0 + a * day, d0 + z * day), ret(bb, d0 + a * day, d0 + z * day)
        out[k] = (c - b) * 1e4 if np.isfinite(c) and np.isfinite(b) else None
    return out


def judge(df: pd.DataFrame, bar: float) -> dict:
    sp = df.index.year.map(split)
    ex = {s: df.loc[sp == s, "ex"].to_numpy() for s in ("TRAIN", "VALID", "TEST")}
    tr = ex["TRAIN"]
    sg = np.sign(tr.mean())
    info = bool(abs(tstat(tr)) >= bar and np.sign(ex["VALID"].mean()) == sg and np.sign(ex["TEST"].mean()) == sg)
    oos = df[sp != "TRAIN"] * sg
    net = lambda c: (float(oos["raw"].mean() - c), float(oos["ex"].mean() - c))
    eco = info and min(net(COST)) > 0 and min(net(STRESS)) > 0
    o = oos["ex"].to_numpy()
    rob = eco and tstat(o - COST) >= 2
    rng = np.random.default_rng(SEED)
    ci = [round(float(np.percentile([rng.choice(o, len(o)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)]
    v = "판정불가" if len(ex["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"
    return {"verdict": v, "sign": int(sg), "t_train": round(tstat(tr), 2),
            **{s: {"n": int((sp == s).sum()), "ex_bp": round(float(df.loc[sp == s, "ex"].mean()), 1),
                   "raw_bp": round(float(df.loc[sp == s, "raw"].mean()), 1), "t": round(tstat(ex[s]), 2)} for s in ("TRAIN", "VALID", "TEST")},
            "oos_ex_bp_signed": round(float(o.mean()), 1), "oos_ex_ci95": ci, "oos_raw_bp_signed": round(float(oos["raw"].mean()), 1),
            "net_raw_ex": [round(x, 1) for x in net(COST)], "net_raw_ex_stress": [round(x, 1) for x in net(STRESS)],
            "t_net_ex": round(tstat(o - COST), 2), "breakeven_bp": round(float(min(oos["raw"].mean(), o.mean())), 1),
            "periods_ex": {g: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)}
                           for g, x in df["ex"].groupby(df.index.year.map(period))},
            "yearly_ex": {int(y): round(float(x), 1) for y, x in df["ex"].groupby(df.index.year).mean().items()}}


def load_close(f: Path, col: str) -> pd.Series:
    d = pd.read_parquet(f)
    return d.set_index(pd.to_datetime(d["date"]).dt.normalize())[col].astype(float)


def main():
    meta = json.loads((D / "listings.json").read_text(encoding="utf-8"))
    bb = load_close(D / "binance_daily" / "BTCUSDT.parquet", "close")
    upbtc = load_close(D / "upbit_krw_daily" / "KRW-BTC.parquet", "trade_price")
    cnt = {"krw_markets": len(meta), "d0_ge_2018": 0, "binance": 0, "not_prior": 0, "price_mismatch": 0, "used": 0}
    rows = []
    for m, v in meta.items():
        d0 = pd.Timestamp(v["first"])
        if d0 < pd.Timestamp("2018-01-01"):
            continue
        cnt["d0_ge_2018"] += 1
        if not v["binance"]:
            continue
        cnt["binance"] += 1
        e = event(d0, load_close(D / "binance_daily" / f"{v['binance']}.parquet", "close"), bb,
                  load_close(D / "upbit_krw_daily" / f"{m}.parquet", "trade_price"), upbtc)
        if isinstance(e, str):
            cnt[e] += 1
            continue
        cnt["used"] += 1
        rows.append({"d0": d0, "market": m, **{f"{k}_raw": e[k][0] if e[k] else np.nan for k in H},
                     **{f"{k}_ex": e[k][1] if e[k] else np.nan for k in H}, "pump_d0": e["pump_d0"], "pre_7_1": e["pre_7_1"]})
    ev = pd.DataFrame(rows)
    ser = {k: ev.dropna(subset=[f"{k}_ex"]).groupby("d0")[[f"{k}_raw", f"{k}_ex"]].mean().set_axis(["raw", "ex"], axis=1) for k in H}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s.loc[s.index.year <= 2021, "ex"].to_numpy() for s in ser.values()], rng)
    rec = {}
    for c in ("pump_d0", "pre_7_1"):
        x = ev.dropna(subset=[c]).groupby("d0")[c].mean()
        rec[c] = {s: {"n": int(len(g)), "bp": round(float(g.mean()), 1), "t": round(tstat(g.to_numpy()), 2)}
                  for s, g in x.groupby(x.index.year.map(split))}
    out = {"bar": round(bar, 2), "counts": cnt, "cells": {k: judge(s, bar) for k, s in ser.items()}, "record": rec,
           "events": ev.assign(d0=ev["d0"].dt.date.astype(str))[["d0", "market"]].values.tolist()}
    (HERE / "upbit-krw-listing.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "events"}, ensure_ascii=False, indent=1))


def selftest():
    idx = pd.date_range("2021-01-01", periods=120)
    bb = pd.Series(np.linspace(100, 110, 120), index=idx)
    cb = pd.Series(10.0, index=idx)
    d0 = idx[50]
    cb.loc[d0 + pd.Timedelta(days=1):] = 9.0                  # 상장 다음 날 10% 하락 후 유지
    upbtc, up = bb * 1300, cb * 1300
    e = event(d0, cb, bb, up, upbtc)
    assert e["U1"][0] > 900 and e["U1"][1] > e["U1"][0]        # 숏 원수익 +10%, BTC 상승분만큼 초과가 더 크다
    assert event(d0, cb, bb, up * 3, upbtc) == "price_mismatch"
    assert event(d0, cb[cb.index >= d0], bb, up, upbtc) == "not_prior"
    assert split(2021) == "TRAIN" and split(2023) == "VALID" and split(2024) == "TEST"
    print("selftest 4/4 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
