#!/usr/bin/env python3
"""CME 주말 갭 메우기 → BTC. 사전등록 findings/cme-gap-preregistration-2026-10.md.

    python research/strategy-lab/futures/cme_gap.py             # 판정(새 수집 없음 — cbprem/bn_btc.parquet)
    python research/strategy-lab/futures/cme_gap.py --selftest
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

SEED = 20261103
CHI = "America/Chicago"
TH = 0.01
H = pd.Timedelta(hours=1)
START, END = pd.Timestamp("2018-01-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")


def weeks() -> pd.DataFrame:
    """금요일마다 T_c(금 16:00 CT) · T_r(일 17:00 CT) · T_c2(다음 금 16:00 CT), UTC."""
    fr = pd.date_range("2017-12-29", "2026-10-02", freq="W-FRI")
    rows = []
    for f in fr:
        tc = pd.Timestamp(f.date()).tz_localize(CHI) + pd.Timedelta(hours=16)
        tr = (pd.Timestamp(f.date()) + pd.Timedelta(days=2)).tz_localize(CHI) + pd.Timedelta(hours=17)
        tc2 = (pd.Timestamp(f.date()) + pd.Timedelta(days=7)).tz_localize(CHI) + pd.Timedelta(hours=16)
        rows.append((tc.tz_convert("UTC"), tr.tz_convert("UTC"), tc2.tz_convert("UTC")))
    return pd.DataFrame(rows, columns=["tc", "tr", "tc2"])


def gaps(o: pd.Series) -> pd.DataFrame:
    w = weeks()
    w["pc"], w["pr"] = o.reindex(w["tc"]).to_numpy(), o.reindex(w["tr"]).to_numpy()
    w["p24"], w["pc2"] = o.reindex(w["tr"] + 24 * H).to_numpy(), o.reindex(w["tc2"]).to_numpy()
    w["G"] = w["pr"] / w["pc"] - 1
    w = w[w[["pc", "pr", "p24", "pc2"]].notna().all(axis=1) & (w["tr"] >= START) & (w["tc2"] < END)]
    w["s"] = -np.sign(w["G"])
    w["G1"] = w["s"] * (w["p24"] / w["pr"] - 1) * 1e4
    w["G5"] = w["s"] * (w["pc2"] / w["pr"] - 1) * 1e4
    w.index = w["tr"].dt.normalize()
    return w


def touch(o: pd.Series, w: pd.DataFrame) -> dict:
    fill = opp = 0
    for _, x in w.iterrows():
        path = o[(o.index > x["tr"]) & (o.index <= x["tc2"])]
        up = x["G"] > 0
        lvl_fill, lvl_opp = x["pc"], x["pr"] * (1 + x["G"])
        fill += bool((path <= lvl_fill).any() if up else (path >= lvl_fill).any())
        opp += bool((path >= lvl_opp).any() if up else (path <= lvl_opp).any())
    n = len(w)
    return {"n": n, "fill%": round(fill / n * 100, 1), "opposite_same_distance%": round(opp / n * 100, 1)}


def brief(r: pd.Series) -> dict:
    return {k: {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)} for k, x in r.groupby(r.index.map(cp.split))}


def main():
    o = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    w = gaps(o)
    ev = w[w["G"].abs() >= TH]
    series = {k: ev[k] for k in ("G1", "G5")}
    rng = np.random.default_rng(SEED)
    bar = null_bar([s[s.index.map(cp.split) == "TRAIN"].to_numpy() for s in series.values()], rng)
    out = {"bar": round(bar, 2), "weeks": int(len(w)), "events": int(len(ev)), "cells": {}}
    for k, s in series.items():
        r = cp.judge(s, bar)
        r["legs"] = {"위 갭(숏)": brief(s[ev["G"] > 0]), "아래 갭(롱)": brief(s[ev["G"] < 0])}
        out["cells"][k] = r
    rec = {"touch_events": touch(o, ev), "touch_by_split": {k: touch(o, x) for k, x in ev.groupby(ev.index.map(cp.split))}}
    rec["all_weeks"] = {k: brief(w[k]) for k in ("G1", "G5")}
    ev2 = w[w["G"].abs() >= 0.02]
    rec["th2%"] = {k: brief(ev2[k]) for k in ("G1", "G5")}
    rec["gap_abs_quantiles%"] = {q: round(float(w["G"].abs().quantile(q) * 100), 2) for q in (0.25, 0.5, 0.75, 0.9)}
    out["record"] = rec
    (HERE / "cme-gap.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    ok = 0
    w = weeks()
    x = w[w["tc"].dt.date.astype(str) == "2024-07-12"].iloc[0]                 # 서머타임: CT = UTC−5
    assert str(x["tc"]) == "2024-07-12 21:00:00+00:00" and str(x["tr"]) == "2024-07-14 22:00:00+00:00"; ok += 1
    y = w[w["tc"].dt.date.astype(str) == "2024-01-12"].iloc[0]                 # 표준시: CT = UTC−6
    assert str(y["tc"]) == "2024-01-12 22:00:00+00:00" and str(y["tr"]) == "2024-01-14 23:00:00+00:00"; ok += 1
    idx = pd.date_range("2024-07-01", "2024-07-31", freq="h", tz="UTC")
    o = pd.Series(100.0, index=idx)
    o[o.index >= x["tr"]] = 102.0                                              # 위 갭 +2%
    o[o.index >= x["tr"] + 24 * H] = 101.0
    g = gaps(o)
    r = g.loc[x["tr"].normalize()]
    assert abs(r["G"] - 0.02) < 1e-12 and r["s"] == -1 and abs(r["G1"] - (-(101 / 102 - 1) * 1e4)) < 1e-9; ok += 1
    t = touch(o, g[g.index == x["tr"].normalize()])
    assert t["fill%"] == 0.0 and t["opposite_same_distance%"] == 0.0; ok += 1  # 101 은 100(메움)·104.04(반대) 어디에도 안 닿음
    print(f"selftest {ok}/4 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
