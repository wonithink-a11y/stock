#!/usr/bin/env python
"""Flat / low-volatility regime study (directive step 12).

Regime definitions (parameterized):
  F1 absolute : OPEN30 range <= thr            (thr grid: 1% / 2%)
  F2 relative : OPEN30 range <= date median    (cross-sectional)
  V  volume   : trailing 20d mean|day ret| of the STOCK below its own
                expanding median (shifted 1 session -> PIT-safe)

Questions:
  Q1 does the regime change SUBSEQUENT volatility (rest-of-day abs excess,
     realized slot ranges after 09:30)?
  Q2 does it change signal strength - here the strongest reversion signal
     found so far (opening surge fade, H5) is evaluated inside/outside the
     flat regime?

Usage: python run_flat_regime.py [--smoke]
Writes findings/flat-regime/{study_results.json,study.md}
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats as sps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intraday import loader, session  # noqa: E402
from intraday.stats import paired_date_diff_ttest, rank_ic_by_date, round_block, summarize  # noqa: E402

SLAB = os.path.join(loader.REPO_ROOT, "research", "strategy-lab")
PANEL_PATH = os.path.join(SLAB, ".cache", "intraday_panel.parquet")
GRID_PATH = os.path.join(SLAB, ".cache", "intraday_grid5m.parquet")
OUT_DIR = os.path.join(SLAB, "findings", "flat-regime")

SLOT_AFTER = ((1000, 1030), (1030, 1130), (1130, 1300),
              (1300, 1400), (1400, 1500), (1500, 1530))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    panel = pd.read_parquet(PANEL_PATH)
    ok = ((panel["n_bars_day"] >= 50) & (panel["day_open"] > 0) &
          (panel["day_close"] > 0) & (panel["day_ret_oc"].abs() <= 0.315) &
          (panel["r30"].abs() <= 0.30) & panel["market"].notna())
    p = panel[ok].reset_index(drop=True)
    if args.smoke:
        dates = sorted(p["date"].unique())[-15:]
        p = p[p["date"].isin(dates)].reset_index(drop=True)

    # trailing own-vol regime (shift(1): past sessions only)
    ps = p.sort_values(["ticker", "date"])
    ps["abs_ret"] = ps["day_ret_oc"].abs()
    ps["vol20"] = ps.groupby("ticker")["abs_ret"].transform(
        lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    med = ps.groupby("date")["vol20"].transform(lambda s: s.expanding().median())
    ps["volLow"] = ps["vol20"] <= med
    p = ps.sort_values(["date", "ticker"]).reset_index(drop=True)

    # afternoon realized ranges from bucket h/l
    marks = [int(m) for m in session.GRID_MARKS]
    cols = ["date", "ticker"]
    for m in marks:
        cols += [f"h{m:04d}", f"l{m:04d}"]
    g = pd.read_parquet(GRID_PATH, columns=cols)
    g = (g.merge(p[["date", "ticker"]], on=["date", "ticker"], how="inner")
          .sort_values(["date", "ticker"]).reset_index(drop=True))
    assert len(g) == len(p)
    pos = {m: k for k, m in enumerate(marks)}
    pm_hi = np.full(len(g), np.nan)
    pm_lo = np.full(len(g), np.nan)
    ks = [pos[m] for m in marks if m > 930]
    pm_hi = g[[f"h{marks[k]:04d}" for k in ks]].max(axis=1).to_numpy(float)
    pm_lo = g[[f"l{marks[k]:04d}" for k in ks]].min(axis=1).to_numpy(float)
    with np.errstate(all="ignore"):
        op_ = p["open_price"].to_numpy(float)
        p["pm_range"] = np.where(op_ > 0, (pm_hi - pm_lo) / op_, np.nan)

    with np.errstate(all="ignore"):
        p["absRest"] = (p["day_close"].astype(float) /
                        p["p_at30m"].astype(float) - 1.0).abs()

    res = {"sample": {"rows": int(len(p)), "days": int(p["date"].nunique())}}
    regimes = {
        "F1_range<=1%": p["w30_range"].fillna(99) <= 0.01,
        "F1_range<=2%": p["w30_range"].fillna(99) <= 0.02,
        "F2_belowDateMedian": None,
        "V_volLow20d": p["volLow"].fillna(False),
        "F1xV_combined": (p["w30_range"].fillna(99) <= 0.02) & p["volLow"].fillna(False),
    }
    med_r = p.groupby("date")["w30_range"].transform("median")
    regimes["F2_belowDateMedian"] = p["w30_range"] <= med_r

    blocks = {}
    for name, mask in regimes.items():
        mask = mask.fillna(False) if isinstance(mask, pd.Series) else mask
        inm, outm = p[mask], p[~mask]
        blk = {}
        for label, sub in (("inRegime", inm), ("outRegime", outm)):
            blk[label] = {
                "n": int(len(sub)),
                "meanAbsRest": float(sub["absRest"].mean()),
                "medianPmRange": float(sub["pm_range"].median()),
                "meanAbsNextDay": float(
                    (sub.groupby("ticker")["day_ret_oc"].shift(0)).abs().mean()),
            }
        blk["absRestDiff_t"] = paired_date_diff_ttest(
            p.reset_index(drop=True), mask.reset_index(drop=True),
            (~mask).reset_index(drop=True), "absRest")["t"]
        # reversion signal strength inside/outside: r30 quintiles -> rest-day
        for label, sub in (("inRegime", inm), ("outRegime", outm)):
            d = sub.dropna(subset=["r30"]).copy()
            d["_q"] = d.groupby("date")["r30"].transform(
                lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5))
            mu = d.groupby(["date", "market"])["absRest"].transform("mean")
            d["_exc_abs"] = d["absRest"] - mu
            q5 = d[d["_q"] == 5]
            q1 = d[d["_q"] == 1]
            blk[label]["reversion_Q5minusQ1_absExc"] = (
                float(q5["_exc_abs"].mean() - q1["_exc_abs"].mean())
                if len(q5) > 100 and len(q1) > 100 else None)
        blocks[name] = blk
    res["regimes"] = blocks

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "smoke" if args.smoke else "full",
        "definitions": {
            "regimes": "F1 absolute w30range thresholds; F2 cross-sectional "
                       "date median; V trailing 20d mean|oc| below expanding "
                       "median (shift1); combined = F1(2%)&V",
            "volMetrics": "absRest=|close/p30-1|; pmRange=(pmHi-pmLo)/open "
                          "over buckets after 09:30",
        },
        "results": res,
        "runtimeSec": round(time.time() - t0, 1),
    }
    out = round_block(out)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "study_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    md = ["# 횡보/저변동 레짐 연구 (step 12)\n",
          "| 레짐 | in n | |잔여당일| | in PM range | out n | out |잔여| | t(absRest) |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for name, b in blocks.items():
        i_, o_ = b["inRegime"], b["outRegime"]
        t_ = b["absRestDiff_t"]
        md.append(f"| {name} | {i_['n']:,} | {i_['meanAbsRest']*100:.3f}% | "
                  f"{i_['medianPmRange']*100:.2f}% | {o_['n']:,} | "
                  f"{o_['meanAbsRest']*100:.3f}% | "
                  f"{t_:+.1f} |" if t_ is not None else
                  f"| {name} | {i_['n']:,} | {i_['meanAbsRest']*100:.3f}% | "
                  f"{i_['medianPmRange']*100:.2f}% | {o_['n']:,} | "
                  f"{o_['meanAbsRest']*100:.3f}% | NA |")
    with open(os.path.join(OUT_DIR, "study.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    print(json.dumps({"mode": out["mode"], "rows": res["sample"]["rows"],
                      "runtimeSec": out["runtimeSec"]}))
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
