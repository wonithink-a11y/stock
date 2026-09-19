#!/usr/bin/env python3
"""KR 밤사이 보유 — 사전등록 findings/kr-overnight-holding-preregistration-2026-09.md.

  python research/strategy-lab/futures/kr_overnight_holding.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import tstat, null_bar  # noqa: E402

COST, COST2 = 30.0, 40.0
a = pd.concat([pd.read_parquet(p) for p in sorted((HERE.parent / ".cache" / "a2a_parquet").glob("*.parquet"))])
a = a[(a.open > 0) & (a.close > 0)].copy()
a["date"] = pd.to_datetime(a.date)
a = a.sort_values(["ticker", "date"])
cal = np.sort(a.date.unique())
a["k"] = a.date.map(pd.Series(np.arange(len(cal)), index=cal))
g = a.groupby("ticker")
a["on"] = np.where(g.k.shift(-1) == a.k + 1, g.open.shift(-1) / a.close - 1, np.nan) * 1e4
a.loc[a.on.abs() > 3000, "on"] = np.nan
a["amt"] = a.close * a.volume
a["liq"] = g.amt.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
r = g.close.pct_change()
a["rv20"] = r.groupby(a.ticker).transform(lambda s: s.shift(1).rolling(20, min_periods=20).std())
a["ret20"] = g.close.transform(lambda s: s.shift(1) / s.shift(21) - 1)
u = a[a.liq >= 2e9].dropna(subset=["rv20", "ret20", "on"]).copy()
for c in ("rv20", "ret20"):
    u[c + "_top"] = u.groupby("date")[c].transform(lambda s: s.rank(pct=True) > 0.8)
cells = {"N1": u[u.rv20_top], "N2": u[u.ret20_top], "N3": u[u.rv20_top & u.ret20_top]}
split = lambda d: "TRAIN" if d.year <= 2020 else ("VALID" if d.year <= 2022 else "TEST")
daily = {k: v.groupby("date").on.mean() for k, v in cells.items()}
parts = {k: {s: s_.to_numpy() for s, s_ in d.groupby(d.index.map(split))} for k, d in daily.items()}
bar = null_bar([parts[k]["TRAIN"] for k in parts], np.random.default_rng(20260922))
out = {"bar": round(bar, 2)}
for k, p in parts.items():
    tr, oos = p["TRAIN"], np.r_[p["VALID"], p["TEST"]]
    s = np.sign(tr.mean())
    info = abs(tstat(tr)) >= bar and np.sign(p["VALID"].mean()) == s and np.sign(p["TEST"].mean()) == s
    eco = info and s > 0 and (oos - COST).mean() > 0 and (oos - COST2).mean() > 0
    rob = eco and tstat(oos - COST) >= 2
    d = daily[k]
    out[k] = {"verdict": "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT",
              "t_train": round(tstat(tr), 2),
              **{sp: round(float(p[sp].mean()), 1) for sp in ("TRAIN", "VALID", "TEST")},
              "net30_oos": round(float((oos - COST).mean()), 1), "t_net30_oos": round(tstat(oos - COST), 2),
              "names_per_day": round(float(cells[k].groupby("date").size().mean()), 1),
              "yearly_net30": {int(y): round(float(v - COST), 1) for y, v in d.groupby(d.index.year).mean().items()},
              "L2_only_mean": round(float(cells[k][cells[k].liq >= 2e10].groupby("date").on.mean().mean()), 1)}
(HERE / "kr-overnight-holding.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
