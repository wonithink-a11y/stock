#!/usr/bin/env python
"""Afternoon crash -> next-day reversal deep dive (directive step 11, H4).

Base event: r(14:00 -> close) <= -thr   (thr grid: 3% / 5% / 7%)

Condition splits (each parameterized, reported separately - never merged
into one tuned rule):
  market vs idiosyncratic : KOSPI EW segment return that day <= -1% or not
  volume                  : rel vol of 14:00-15:00 >= 2.0 vs < 1.0
  close position          : close within 1% of day low vs > 3% away
  morning state           : OPEN30 range <= 2% (calm start) vs >= 4%

Next-session outcomes measured FROM TODAY'S CLOSE (the only price a trader
can act on at 15:30): next open, next 09:35, next 10:30, next close.

Usage: python run_afternoon_crash.py [--smoke]
Writes findings/afternoon-crash-nextday/{study_results.json,study.md}
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
from intraday import loader, market  # noqa: E402
from intraday.stats import round_block, summarize  # noqa: E402

SLAB = os.path.join(loader.REPO_ROOT, "research", "strategy-lab")
PANEL_PATH = os.path.join(SLAB, ".cache", "intraday_panel.parquet")
GRID_PATH = os.path.join(SLAB, ".cache", "intraday_grid5m.parquet")
OUT_DIR = os.path.join(SLAB, "findings", "afternoon-crash-nextday")

THRS = (-0.03, -0.05, -0.07)


def load_aligned(panel, marks_needed):
    cols = ["date", "ticker"] + [f"c{m:04d}" for m in marks_needed]
    grid = pd.read_parquet(GRID_PATH, columns=cols)
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)
    grid = (grid.merge(panel[["date", "ticker"]], on=["date", "ticker"],
                       how="inner")
                .sort_values(["date", "ticker"]).reset_index(drop=True))
    if len(grid) != len(panel):
        raise RuntimeError("grid/panel key mismatch")
    return grid


def attach_next_prices(f, grid_full, marks_needed):
    """Join NEXT session's grid closes using pure adjacency on sorted rows."""
    g = grid_full[["date", "ticker"] + [f"c{m:04d}" for m in (930, 935, 1030)]]
    g = g.sort_values(["ticker", "date"]).reset_index(drop=True)
    tk = g["ticker"].to_numpy()
    same = np.empty(len(tk), dtype=bool)
    same[:-1] = tk[:-1] == tk[1:]
    same[-1] = False
    idx = np.where(same)[0]
    nxt = pd.DataFrame({
        "ticker": tk[idx],
        "date": g["date"].to_numpy()[idx],          # prev session
        "n_c0930": g["c0930"].to_numpy()[idx + 1],
        "n_c0935": g["c0935"].to_numpy()[idx + 1],
        "n_c1030": g["c1030"].to_numpy()[idx + 1],
    })
    return f.merge(nxt, on=["ticker", "date"], how="left")


def cell_stats(f, mask, outs, label):
    sub = f[mask.reindex(f.index).fillna(False)]
    blk = {"n": int(len(sub))}
    for oc in outs:
        st = summarize(sub[oc])
        mu = f.dropna(subset=[oc]).groupby(["date", "market"])[oc].transform("mean")
        exc = (sub[oc] - mu.reindex(sub.index)).dropna()
        if len(exc):
            st["meanExc"] = float(exc.mean())
            st["winRateExc"] = float((exc > 0).mean())
            if len(exc) > 1 and exc.std(ddof=1) > 0:
                t, pv = sps.ttest_1samp(exc.to_numpy(), 0.0)
                st["tExc"], st["pExc"] = float(t), float(pv)
            st["nExc"] = int(len(exc))
        blk[oc] = st
    return blk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    panel = pd.read_parquet(PANEL_PATH)
    ok = ((panel["n_bars_day"] >= 50) & (panel["day_open"] > 0) &
          (panel["day_close"] > 0) & (panel["day_high"] >= panel["day_low"]) &
          (panel["day_ret_oc"].abs() <= 0.315) &
          (panel["r30"].abs() <= 0.30) & panel["market"].notna())
    panel = panel[ok].reset_index(drop=True)
    if args.smoke:
        dates = sorted(panel["date"].unique())[-15:]
        panel = panel[panel["date"].isin(dates)].reset_index(drop=True)
    # load_aligned sorts by (date,ticker) to align with the grid; the frame
    # used for feature assignment must share that exact order.
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)

    grid = load_aligned(panel, (930, 935, 1030, 1400, 1500, 1530))
    f = panel[["date", "ticker", "market", "day_open", "day_close", "day_low",
               "w30_range", "rel_v_w1400_1500"]].copy()
    with np.errstate(all="ignore"):
        c1400 = grid["c1400"].to_numpy(dtype=float)
        c1530 = grid["c1530"].to_numpy(dtype=float)
        dc = f["day_close"].to_numpy(dtype=float)
        dl = f["day_low"].to_numpy(dtype=float)
        f["r_1400_close"] = np.where(c1400 > 0, c1530 / c1400 - 1.0, np.nan)
        f["nearLow"] = np.where(dl > 0, (dc - dl) / dl, np.nan)

    # market regime + next-day prices
    regimes = market.day_regimes(panel)
    f = market.attach_regimes(f, regimes)
    from intraday.forward import build_next_day
    nd = build_next_day(panel)
    f = f.merge(nd, on=["ticker", "date"], how="left")
    f = attach_next_prices(f, grid, (930, 935, 1030))
    with np.errstate(all="ignore"):
        f["n_open"] = f["next_open"] / f["day_close"] - 1.0
        f["n_0935"] = f["n_c0935"] / f["day_close"] - 1.0
        f["n_1030"] = f["n_c1030"] / f["day_close"] - 1.0
        f["n_close"] = f["next_close"] / f["day_close"] - 1.0

    OUTS = ("n_open", "n_0935", "n_1030", "n_close")

    res = {}
    for thr in THRS:
        base = f["r_1400_close"].fillna(0) <= thr
        blk = {"base": cell_stats(f, base, OUTS, f"thr{thr}")}
        kr = f["reg_kospi_ret"]
        blk["marketCrashDay(kospi<=-1%)"] = cell_stats(
            f, base & (kr <= -0.01), OUTS, "")
        blk["idioDay(kospi>-1%)"] = cell_stats(
            f, base & (kr > -0.01), OUTS, "")
        rv = f["rel_v_w1400_1500"]
        blk["volHi(rv>=2)"] = cell_stats(f, base & (rv >= 2.0), OUTS, "")
        blk["volLo(rv<1)"] = cell_stats(f, base & (rv < 1.0), OUTS, "")
        nl = f["nearLow"]
        blk["closedAtLow(<=1%)"] = cell_stats(f, base & (nl <= 0.01), OUTS, "")
        blk["offLow(>3%)"] = cell_stats(f, base & (nl > 0.03), OUTS, "")
        wr = f["w30_range"]
        blk["calmOpen(range<=2%)"] = cell_stats(
            f, base & (wr <= 0.02), OUTS, "")
        blk["wildOpen(range>=4%)"] = cell_stats(
            f, base & (wr >= 0.04), OUTS, "")
        res[f"thr={abs(thr):.0%}"] = blk

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "smoke" if args.smoke else "full",
        "definitions": {
            "event": "r(14:00->close) <= -thr; outcomes from today's close",
            "outcomes": "n_open/n_0935/n_1030/n_close = next session "
                        "open/09:35/10:30/close over today close",
            "splits": "market day vs idiosyncratic via KOSPI-EW segment ret; "
                      "volume via rel_v_w1400_1500; position via close-to-low; "
                      "morning via OPEN30 range",
            "excess": "same-date EW segment benchmark over eligible universe",
        },
        "sample": {"rows": int(len(f)), "days": int(f["date"].nunique())},
        "results": res,
        "pitNote": "conditions use <=15:30 data; outcomes strictly next day",
        "runtimeSec": round(time.time() - t0, 1),
    }
    out = round_block(out)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "study_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    md = ["# 오후 급락 -> 다음날 반등? (step 11)\n",
          f"rows={out['sample']['rows']:,}\n",
          "| 조건 | n | 다음시가 | +10:35까지 | +10:30까지 | 다음날종가 |",
          "|---|---:|---:|---:|---:|---:|"]
    for tk_, blk in res.items():
        b = blk["base"]
        md.append("| **{}** | {:,} | {:+.2f}% | {:+.2f}% | {:+.2f}% | {:+.2f}% |".format(
            tk_, b["n"],
            (b["n_open"]["meanExc"] or 0) * 100,
            (b["n_0935"]["meanExc"] or 0) * 100,
            (b["n_1030"]["meanExc"] or 0) * 100,
            (b["n_close"]["meanExc"] or 0) * 100))
        for cond in ("marketCrashDay(kospi<=-1%)", "idioDay(kospi>-1%)",
                     "volHi(rv>=2)", "volLo(rv<1)", "closedAtLow(<=1%)",
                     "offLow(>3%)", "calmOpen(range<=2%)", "wildOpen(range>=4%)"):
            s = blk.get(cond, {}).get("n_close", {})
            if s.get("n"):
                md.append(f"| · {cond} | {s['n']:,} | | | | "
                          f"{(s.get('meanExc') or 0)*100:+.2f}% (t={s.get('tExc', float('nan')):+.1f}) |")
    with open(os.path.join(OUT_DIR, "study.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    print(json.dumps({"mode": out["mode"], "rows": out["sample"]["rows"],
                      "runtimeSec": out["runtimeSec"]}))
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
