#!/usr/bin/env python3
"""크립토 단기 신호 — 사전등록 findings/crypto-short-horizon-preregistration-2026-09.md.

    python research/strategy-lab/futures/crypto_short_horizon.py            # 실행
    python research/strategy-lab/futures/crypto_short_horizon.py --selftest
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import tstat, null_bar  # noqa: E402

DATA = HERE.parent / "data" / "crypto"
COST_N, COST_F = 10.0, 3.0
SEED = 20260923
H = pd.Timedelta(hours=1)


def split(t: pd.Timestamp) -> str:
    return "TRAIN" if t.year <= 2022 else ("VALID" if t.year == 2023 else "TEST")


def load() -> dict:
    coins = {}
    for f in sorted(glob.glob(str(DATA / "basis" / "1h" / "*_1h.parquet"))):
        sym = Path(f).name.replace("_1h.parquet", "")
        d = pd.read_parquet(f, columns=["time", "mark_open", "premium_close"]).set_index("time").sort_index()
        d = d[~d.index.duplicated()].asfreq("1h")
        fu = pd.read_parquet(DATA / "funding" / f"{sym}.parquet")["fundingRate"].astype(float)
        fu.index = pd.to_datetime(fu.index).floor("h")
        fu = fu[~fu.index.duplicated(keep="last")].sort_index()
        coins[sym] = (d, fu)
    return coins


def features(d: pd.DataFrame, fu: pd.Series) -> pd.DataFrame:
    p = d["mark_open"]
    f = pd.DataFrame({"p": p})
    f["r4"] = p / p.shift(4) - 1
    f["r24"] = p / p.shift(24) - 1
    f["r1"] = p / p.shift(1) - 1
    grid = f.index.hour % 4 == 0
    s4 = f.loc[grid, "r4"].shift(1).rolling(180, min_periods=90).std()
    s24 = f.loc[grid, "r24"].shift(1).rolling(180, min_periods=90).std()
    f["s4"], f["s24"] = s4.reindex(f.index), s24.reindex(f.index)
    fpct = fu.rolling(271, min_periods=100).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
    apct = fu.abs().rolling(271, min_periods=100).apply(lambda x: (x[:-1] < x[-1]).mean(), raw=True)
    f["fund"] = fu.reindex(f.index, method="ffill")
    f["fpct"] = fpct.reindex(f.index, method="ffill")
    f["apct"] = apct.reindex(f.index, method="ffill")
    f["settle"] = f.index.isin(fu.index)
    pr = d["premium_close"]
    f["pz"] = (pr - pr.shift(1).rolling(720, min_periods=360).mean()) / pr.shift(1).rolling(720, min_periods=360).std()
    return f


def seq(f: pd.DataFrame, cond: np.ndarray, direction: np.ndarray, h: int) -> list:
    p = f["p"].to_numpy()
    idx = f.index
    out, i, n = [], 0, len(f)
    hits = np.flatnonzero(cond)
    last = -1
    for i in hits:
        if i <= last or i + h >= n or not np.isfinite(p[i]) or not np.isfinite(p[i + h]):
            continue
        out.append((idx[i], direction[i] * (p[i + h] / p[i] - 1) * 1e4))
        last = i + h
    return out


def coin_events(f: pd.DataFrame, btc: pd.DataFrame | None) -> dict:
    g4 = f.index.hour % 4 == 0
    r4, r24, s4, s24 = (f[k].to_numpy() for k in ("r4", "r24", "s4", "s24"))
    fp, ap, pz = f["fpct"].to_numpy(), f["apct"].to_numpy(), f["pz"].to_numpy()
    up4, dn4 = g4 & (r4 > 2 * s4), g4 & (r4 < -2 * s4)
    one, neg = np.ones(len(f)), -np.ones(len(f))
    ev = {"C1": seq(f, dn4 & (fp < 0.1), one, 12), "C2": seq(f, up4 & (fp > 0.9), neg, 12),
          "C3": seq(f, dn4 & (pz < -2), one, 12), "C4": seq(f, up4 & (pz > 2), neg, 12)}
    st = f["settle"].to_numpy()
    pre = r4                                    # T−4h → T
    ev["C5"] = seq(f, st & (ap > 0.9) & (pre != 0) & np.isfinite(pre), -np.sign(np.nan_to_num(pre)), 4)
    c6 = st & ((fp > 0.9) | (fp < 0.1))
    ev["C6"] = seq(f, c6, np.where(fp > 0.9, -1.0, 1.0), 8)
    ev["C7"] = seq(f, g4 & (np.abs(r24) > 2 * s24), np.sign(np.nan_to_num(r24)), 12)
    ev["C8"] = seq(f, g4 & (np.abs(r4) > 2 * s4), np.sign(np.nan_to_num(r4)), 4)
    if btc is not None:
        b = btc["r1"].reindex(f.index).to_numpy()
        a = f["r1"].to_numpy()
        lag = (np.abs(b) >= 0.015) & np.isfinite(a) & (np.sign(b) * a < 0.5 * np.abs(b))
        ev["C9"] = seq(f, lag, np.sign(np.nan_to_num(b)), 4)
    return ev


def c10(feats: dict) -> list:
    px = pd.DataFrame({k: v["p"] for k, v in feats.items()})
    mondays = px.index[(px.index.dayofweek == 0) & (px.index.hour == 0)]
    out = []
    for i, t in enumerate(mondays[:-1]):
        t0, t1 = t - pd.Timedelta(weeks=8), mondays[i + 1]
        if t0 not in px.index:
            continue
        past = (px.loc[t] / px.loc[t0] - 1).dropna()
        fwd = (px.loc[t1] / px.loc[t] - 1).reindex(past.index).dropna()
        past = past.reindex(fwd.index)
        if len(past) < 5:
            continue
        q = past.rank(pct=True)
        lo, hi = fwd[q <= 0.2], fwd[q > 0.8]
        if len(lo) and len(hi):
            out.append((t, (lo.mean() - hi.mean()) * 1e4))
    return out


def aggregate(events: list) -> pd.Series:
    if not events:
        return pd.Series(dtype=float)
    s = pd.DataFrame(events, columns=["t", "v"]).groupby("t")["v"].mean()
    return s.sort_index()


def judge(s: pd.Series, bar: float, info_only=False) -> dict:
    parts = {k: v.to_numpy() for k, v in s.groupby(s.index.map(split))}
    for k in ("TRAIN", "VALID", "TEST"):
        parts.setdefault(k, np.array([]))
    tr = parts["TRAIN"]
    sg = np.sign(tr.mean()) if len(tr) else 0
    info = (abs(tstat(tr)) >= bar and len(parts["VALID"]) and len(parts["TEST"])
            and np.sign(parts["VALID"].mean()) == sg and np.sign(parts["TEST"].mean()) == sg)
    oos = sg * np.r_[parts["VALID"], parts["TEST"]]
    net = lambda c: float((oos - c).mean()) if len(oos) else np.nan
    eco_n = bool(info) and not info_only and net(COST_N) > 0 and net(2 * COST_N) > 0
    eco_f = bool(info) and not info_only and net(COST_F) > 0 and net(2 * COST_F) > 0
    rob = eco_n and tstat(oos - COST_N) >= 2
    v = ("판정불가" if len(parts["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC-보통" if eco_n
         else "ECONOMIC-무료이벤트" if eco_f else "INFORMATION" if info else "REJECT")
    return {"verdict": v, "sign": int(sg), "t_train": round(tstat(tr), 2),
            **{k: {"n": len(parts[k]), "bp": round(float(parts[k].mean()), 2) if len(parts[k]) else None,
                   "t": round(tstat(parts[k]), 2)} for k in ("TRAIN", "VALID", "TEST")},
            "net10_oos": round(net(COST_N), 2), "net3_oos": round(net(COST_F), 2),
            "t_net10_oos": round(tstat(oos - COST_N), 2) if len(oos) > 2 else None}


def main():
    coins = load()
    feats = {k: features(d, fu) for k, (d, fu) in coins.items()}
    btc = feats["BTCUSDT"]
    allev = {}
    for k, f in feats.items():
        for cid, ev in coin_events(f, None if k == "BTCUSDT" else btc).items():
            allev.setdefault(cid, []).extend(ev)
    allev["C10"] = c10(feats)
    series = {c: aggregate(allev[c]) for c in sorted(allev, key=lambda x: int(x[1:]))}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "coins": len(coins),
           "span": [str(min(f.index[0] for f in feats.values())), str(max(f.index[-1] for f in feats.values()))],
           "events": {c: len(allev[c]) for c in allev},
           "cells": {c: judge(s, bar, info_only=(c == "C10")) for c, s in series.items()}}
    for c, s in series.items():
        out["cells"][c]["yearly_bp"] = {int(y): round(float(v), 1)
                                        for y, v in (s * out["cells"][c]["sign"]).groupby(s.index.year).mean().items()}
    (HERE / "crypto-short-horizon.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("bar", out["bar"], "coins", out["coins"], out["span"])
    for c, r in out["cells"].items():
        print(f"{c:4s} {r['verdict']:14s} s{r['sign']:+d} tTR {r['t_train']:6.2f} "
              f"n {r['TRAIN']['n']}/{r['VALID']['n']}/{r['TEST']['n']} "
              f"bp {r['TRAIN']['bp']}/{r['VALID']['bp']}/{r['TEST']['bp']} net10 {r['net10_oos']} net3 {r['net3_oos']} "
              f"tnet10 {r['t_net10_oos']}")
        print("     yearly", r["yearly_bp"])


def selftest():
    idx = pd.date_range("2020-01-01", periods=24 * 400, freq="h", tz="UTC")
    rng = np.random.default_rng(1)
    p = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.005, len(idx)))), index=idx)
    d = pd.DataFrame({"mark_open": p, "premium_close": rng.normal(0, 1e-4, len(idx))}, index=idx)
    fu = pd.Series(rng.normal(1e-4, 1e-4, len(idx[::8])), index=idx[::8])
    f = features(d, fu)
    ev = coin_events(f, f)
    assert all(abs(tstat(np.array([e[1] for e in v]))) < 4 for v in ev.values() if len(v) > 10), "잡음에서 신호"
    # 비중첩
    for v in ev.values():
        ts = [e[0] for e in v]
        assert all(b > a for a, b in zip(ts, ts[1:]))
    # 확실한 반전을 심으면 C8 이 음(=반전)으로 잡혀야 한다
    q = p.copy().to_numpy()
    for i in range(200, len(q) - 8, 97):
        q[i:i + 4] *= 1.08                                  # 4h 급등 후 되돌림
    d2 = d.assign(mark_open=q)
    f2 = features(d2, fu)
    c8 = [e[1] for e in coin_events(f2, None)["C8"]]
    assert np.mean(c8) < 0, np.mean(c8)
    print("selftest 3/3 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
