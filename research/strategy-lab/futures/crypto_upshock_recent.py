#!/usr/bin/env python3
"""findings/crypto-upshock-recent-preregistration-2026-09.md.

  python research/strategy-lab/futures/crypto_upshock_recent.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import tstat  # noqa: E402
from crypto_short_horizon import load  # noqa: E402

coins = load()
px = pd.DataFrame({k: d["mark_open"] for k, (d, _) in coins.items()})
px = px[px.index.hour == 0]
px = px[(px.index >= "2019-12-01")]
r = px.pct_change(fill_method=None)
sd = r.shift(1).rolling(30, min_periods=20).std()
nxt = px.shift(-1) / px - 1
sig = (r > 2 * sd) & nxt.notna()
sig = sig[sig.index >= "2020-01-01"]
ev = nxt.where(sig).stack() * 1e4
day = ev.groupby(level=0).mean()
net = day - 10


def perf(x):
    x = x.fillna(0)
    eq = (1 + x).cumprod()
    yrs = len(x) / 365
    return {"CAGR_pct": round(float((eq.iloc[-1] ** (1 / yrs) - 1) * 100), 1),
            "MDD_pct": round(float((eq / eq.cummax() - 1).min() * 100), 1),
            "Sharpe": round(float(x.mean() / x.std() * np.sqrt(365)), 2) if x.std() > 0 else None}


idx = r.index[r.index >= "2020-01-01"][:-1]
port = {}
for c in (10, 3):
    p = (nxt.where(sig).mean(axis=1) - c / 1e4).reindex(idx)
    p[~sig.reindex(idx).any(axis=1)] = 0.0
    port[f"cost{c}"] = perf(p)
port["BTC_buyhold"] = perf(nxt["BTCUSDT"].reindex(idx))
port["EW28_daily"] = perf(nxt.reindex(idx).mean(axis=1))
port["exposure_days_pct"] = round(float(sig.reindex(idx).any(axis=1).mean() * 100), 1)
late = day[day.index >= "2023-01-01"]
out = {"events": int(len(ev)), "obs_days": int(len(day)), "bp": round(float(day.mean()), 2), "t_net10": round(tstat(net.to_numpy()), 2),
       "late_2023_bp": round(float(late.mean()), 2), "late_t": round(tstat(late.to_numpy()), 2),
       "yearly_bp": {int(y): round(float(v), 1) for y, v in day.groupby(day.index.year).mean().items()},
       "portfolio": port}
a = day.mean() - 10 > 0
out["verdict"] = "CONFIRMED" if a and tstat(net.to_numpy()) >= 2 and late.mean() > 10 else ("PARTIAL" if a else "NOT CONFIRMED")
(HERE / "crypto-upshock-recent.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
