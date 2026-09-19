#!/usr/bin/env python3
"""후속 — findings/followup-overnight-futures-crypto-hour-preregistration-2026-09.md.

  python research/strategy-lab/futures/followup_overnight_hour.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import tstat, load_daily  # noqa: E402
from crypto_short_horizon import load, split  # noqa: E402

out = {}
# ---- H-FON
f = load_daily()
same = f["code"] == f["code"].shift(-1)
cost = 26_000 / (f["c"] * 250_000) * 1e4
d = pd.DataFrame({"on": np.where(same, (f["o"].shift(-1) / f["c"] - 1) * 1e4, np.nan),
                  "intra": (f["c"] / f["o"] - 1) * 1e4, "cost": cost,
                  "cc": np.where(f["code"] == f["code"].shift(1), (f["c"] / f["c"].shift(1) - 1) * 1e4, np.nan)},
                 index=f.index)


def perf(x, per_year=250):
    x = x.dropna() / 1e4
    return {"ann_ret_pct": round(float(x.mean() * per_year * 100), 2), "ann_vol_pct": round(float(x.std() * np.sqrt(per_year) * 100), 2),
            "sharpe": round(float(x.mean() / x.std() * np.sqrt(per_year)), 2)}


res = {}
for name, sl in (("2010-2015", d[:"2015-12-31"]), ("2016-", d["2016-01-01":])):
    net = sl["on"] - sl["cost"]
    res[name] = {"overnight_bp": round(float(sl["on"].mean()), 2), "intraday_bp": round(float(sl["intra"].mean()), 2),
                 "cost_bp": round(float(sl["cost"].mean()), 2), "net_bp": round(float(net.mean()), 2), "t_net": round(tstat(net.dropna().to_numpy()), 2),
                 "overnight_only": perf(net), "buy_hold": perf(sl["cc"]),
                 "yearly_on_intra": {int(y): [round(float(a), 1), round(float(b), 1)] for y, (a, b) in sl[["on", "intra"]].groupby(sl.index.year).mean().iterrows()}}
h = res["2010-2015"]
a, b = h["net_bp"] > 0 and h["t_net"] >= 2, h["overnight_bp"] > h["intraday_bp"]
res["verdict"] = "REPLICATED" if a and b else ("PARTIAL" if a or b else "NOT REPLICATED")
out["H-FON"] = res

# ---- H-CH
coins = load()
rets = pd.DataFrame({k: dd["mark_open"].shift(-1) / dd["mark_open"] - 1 for k, (dd, _) in coins.items()}) * 1e4
ew = rets.mean(axis=1).dropna()
ew = ew[ew.index >= "2020-01-01"]
tab = {}
for hr in range(24):
    s = ew[ew.index.hour == hr]
    parts = {k: v.to_numpy() for k, v in s.groupby(s.index.map(split))}
    tab[hr] = {k: (round(float(v.mean()), 2), round(tstat(v), 2)) for k, v in parts.items()}
sel = {hr: v for hr, v in tab.items() if abs(v["TRAIN"][1]) >= 3}
verd = {}
for hr, v in sel.items():
    sg = np.sign(v["TRAIN"][0])
    s = ew[ew.index.hour == hr]
    oos = sg * s[s.index.year >= 2023].to_numpy()
    keep = np.sign(v["VALID"][0]) == sg and np.sign(v["TEST"][0]) == sg
    verd[hr] = {"sign": int(sg), "oos_bp": round(float(oos.mean()), 2), "t_oos": round(tstat(oos), 2),
                "verdict": ("ECONOMIC-보통" if keep and (oos - 10).mean() > 0 else "ECONOMIC-무료이벤트" if keep and (oos - 3).mean() > 0
                            else "INFORMATION" if keep else "REJECT")}
out["H-CH"] = {"by_hour": tab, "selected": verd or "NO SIGNAL"}
(HERE / "followup-overnight-hour.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({"H-FON": {k: v for k, v in res.items() if k != "x"}, "H-CH selected": out["H-CH"]["selected"]}, ensure_ascii=False, indent=1))
print({hr: v["TRAIN"] for hr, v in tab.items()})
