#!/usr/bin/env python3
"""재현 — findings/replication-s5-crypto-upshock-preregistration-2026-09.md.

  python research/strategy-lab/futures/replication_s5_cup.py
"""
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import short_horizon_phase2 as p2  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

out = {}
# ---- R-S5: 같은 코드, 캐시 경로만 연구 창 이후 격자로
p2.CACHE = HERE.parent / ".cache" / "fwd_oos"
meta, A = p2.load_grid()
keep = (meta["date"] >= "2026-08-27").to_numpy()
meta = meta[keep].reset_index(drop=True)
A = {k: v[keep] for k, v in A.items()}
cells, counts, _ = p2.s_events(meta, A)
s5 = pd.DataFrame(cells["S5"], columns=["d", "i", "g", "c"])      # 통계량은 이미 되돌림 방향(-1 곱)
x, g = s5["i"].to_numpy(), s5["g"].to_numpy()
out["R-S5"] = {"days": int(meta["date"].nunique()), "obs_days": len(s5), "events": counts["S5"],
               "excess_bp": round(float(x.mean()), 2), "t": round(tstat(x), 2),
               "gross_bp": round(float(g.mean()), 2), "holder_net30_bp": round(float((g - 30).mean()), 2),
               "verdict": "REPLICATED" if x.mean() > 0 and tstat(x) >= 2 else ("PARTIAL" if x.mean() > 0 else "NOT REPLICATED")}

# ---- R-CUP
ev = {"UP": [], "DN": []}
for f in sorted(glob.glob(str(HERE.parent / ".cache" / "market_data" / "crypto_*_pre2020.parquet"))):
    c = pd.read_parquet(f)["Close"].astype(float)
    c = c[c.index >= "2014-12-01"]
    r = c.pct_change()
    sd = r.shift(1).rolling(30, min_periods=20).std()
    nxt = c.shift(-1) / c - 1
    for t in r.index[(r > 2 * sd) & nxt.notna() & (r.index >= "2015-01-01")]:
        ev["UP"].append((t, nxt[t] * 1e4))
    for t in r.index[(r < -2 * sd) & nxt.notna() & (r.index >= "2015-01-01")]:
        ev["DN"].append((t, -nxt[t] * 1e4))
res = {}
for k, v in ev.items():
    s = pd.DataFrame(v, columns=["t", "x"]).groupby("t")["x"].mean()
    res[k] = {"events": len(v), "obs_days": len(s), "bp": round(float(s.mean()), 2), "t": round(tstat(s.to_numpy()), 2),
              "net10_bp": round(float(s.mean() - 10), 2),
              "yearly": {int(y): round(float(m), 1) for y, m in s.groupby(s.index.year).mean().items()}}
u = res["UP"]
res["verdict"] = "REPLICATED" if u["bp"] > 0 and u["t"] >= 2 else ("PARTIAL" if u["bp"] > 0 else "NOT REPLICATED")
out["R-CUP"] = res
(HERE / "replication-s5-cup.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
