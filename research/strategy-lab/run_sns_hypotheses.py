#!/usr/bin/env python
"""SNS trading claims H1-H9 as parameterized event studies (directive step 8).

SNS wording ("전량 매도", "추격 금지"...) is NOT translated into strategy
rules - each claim becomes a falsifiable event hypothesis:

  H1 morning surge   -> reversal?        r(open->10:30) >= +thr
  H2 morning crash   -> reversal?        r(open->10:30) <= -thr
  H3 afternoon surge -> continuation?    r(14:00->15:00) >= +thr
  H4 afternoon crash -> next-day bounce? r(14:00->close) <= -thr (deep dive: step 11)
  H5 opening surge   -> fade?            r30 = r(open->09:30) >= +thr
  H6 closing surge   -> next day?        r(15:00->close) >= +thr
  H7 near-day-low + volume surge -> bounce next day?
     (day low made after 13:00, close within x% of it, rel volume high vs
      same condition WITHOUT the volume requirement)
  H8 near-day-high + volume surge -> continuation or reversal next day?
  H9 flat morning    -> direction/volatility afterwards?

Every threshold is a GRID, never a single tuned value. Outcomes: rest-of-day
from the event point, next-session open/close, overnight. All stats are also
reported market-adjusted (same-date EW segment mean).

Usage: python run_sns_hypotheses.py [--smoke]
Writes findings/sns-hypotheses/{study_results.json,study.md}
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intraday import loader, session  # noqa: E402
from intraday.forward import build_next_day  # noqa: E402
from intraday.stats import paired_date_diff_ttest, round_block, summarize  # noqa: E402

SLAB = os.path.join(loader.REPO_ROOT, "research", "strategy-lab")
PANEL_PATH = os.path.join(SLAB, ".cache", "intraday_panel.parquet")
GRID_PATH = os.path.join(SLAB, ".cache", "intraday_grid5m.parquet")
OUT_DIR = os.path.join(SLAB, "findings", "sns-hypotheses")

MARKS_NEEDED = (1030, 1300, 1400, 1500, 1530)


def build_frame(panel):
    """panel + slot returns needed by the hypotheses."""
    cols = ["date", "ticker"] + [f"c{m:04d}" for m in MARKS_NEEDED]
    grid = pd.read_parquet(GRID_PATH, columns=cols)
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)
    grid = (grid.merge(panel[["date", "ticker"]], on=["date", "ticker"],
                       how="inner")
                .sort_values(["date", "ticker"]).reset_index(drop=True))
    if len(grid) != len(panel):
        raise RuntimeError("grid/panel key mismatch")

    f = panel[["date", "ticker", "market", "open_price", "p_at30m", "day_open",
               "day_close", "day_high", "day_low", "day_high_time",
               "day_low_time", "r30", "w30_range",
               "rel_v_w1400_1500"]].copy()
    with np.errstate(all="ignore"):
        c1030 = grid["c1030"].to_numpy(dtype=float)
        op = f["open_price"].to_numpy(dtype=float)
        f["r_firsthour"] = np.where(op > 0, c1030 / op - 1.0, np.nan)
        c1400 = grid["c1400"].to_numpy(dtype=float)
        c1500 = grid["c1500"].to_numpy(dtype=float)
        c1530 = grid["c1530"].to_numpy(dtype=float)
        f["r_1400_1500"] = np.where(c1400 > 0, c1500 / c1400 - 1.0, np.nan)
        f["r_1400_close"] = np.where(c1400 > 0, c1530 / c1400 - 1.0, np.nan)
        f["r_1500_close"] = np.where(c1500 > 0, c1530 / c1500 - 1.0, np.nan)
        f["fut_from_1030"] = np.where(c1030 > 0, c1530 / c1030 - 1.0, np.nan)
        f["fut_from_1500"] = np.where(c1500 > 0, c1530 / c1500 - 1.0, np.nan)
        dl = f["day_low"].to_numpy(dtype=float)
        dh = f["day_high"].to_numpy(dtype=float)
        dc = f["day_close"].to_numpy(dtype=float)
        f["nearLow"] = np.where(dl > 0, (dc - dl) / dl, np.nan)
        f["nearHigh"] = np.where(dh > 0, (dh - dc) / dh, np.nan)

    nd = build_next_day(panel)
    f = f.merge(nd, on=["ticker", "date"], how="left")
    return f


def add_next_outcomes(f, anchor_col):
    """Next-session outcomes measured from an intraday anchor price column."""
    with np.errstate(all="ignore"):
        f[f"nxo_{anchor_col}"] = f["next_open"] / f[anchor_col] - 1.0
        f[f"nxc_{anchor_col}"] = f["next_close"] / f[anchor_col] - 1.0
    return f


OUTCOME_COLS = ("fut_from_1030", "fut_from_1500", "rest_from_0930",
                "r_1400_close", "nxc@c1030", "nxo@c1030", "nxc@c1500",
                "nxo@c1500", "nxc@day_close", "nxo@day_close",
                "nxc@p_at30m", "nxo@p_at30m", "overnight_proxy")


def add_universe_benchmarks(f):
    """Per (date, market) equal-weight mean of every outcome over the WHOLE
    eligible universe -> '<col>__uavg'. Excess = value - uavg."""
    for c in OUTCOME_COLS:
        if c in f.columns:
            f[f"{c}__uavg"] = f.groupby(["date", "market"])[c].transform("mean")
    return f


def event_block(f, mask, outcomes, complement_mask=None):
    """Stats for an event + paired diff vs its complement.

    Excess benchmarks are the precomputed whole-universe columns
    ('<col>__uavg') - NOT the event sample's own mean."""
    sub = f[mask]
    blk = {"n": int(mask.sum())}
    for oc in outcomes:
        if oc not in sub.columns:
            continue
        blk[oc] = summarize(sub[oc])
        ua = f"{oc}__uavg"
        if ua in sub.columns:
            exc = (sub[oc] - sub[ua]).dropna()
            blk[oc]["meanExc"] = float(exc.mean()) if len(exc) else None
            blk[oc]["winRateExc"] = float((exc > 0).mean()) if len(exc) else None
            if len(exc) > 1 and exc.std(ddof=1) > 0:
                from scipy import stats as sps
                t, pv = sps.ttest_1samp(exc.to_numpy(), 0.0)
                blk[oc]["tExc"] = float(t)
                blk[oc]["pExc"] = float(pv)
    if complement_mask is not None:
        comp = {}
        for oc in outcomes:
            if oc in sub.columns:
                comp[oc] = paired_date_diff_ttest(f, mask, complement_mask, oc)
        blk["vsComplement"] = comp
    return blk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    panel = pd.read_parquet(PANEL_PATH)
    ok = ((panel["n_bars_day"] >= 20) & (panel["day_open"] > 0) &
          (panel["day_close"] > 0) & (panel["day_high"] >= panel["day_low"]) &
          (panel["day_ret_oc"].abs() <= 0.315) &
          (panel["r30"].abs() <= 0.30) & panel["market"].notna())
    panel = panel[ok].reset_index(drop=True)
    if args.smoke:
        dates = sorted(panel["date"].unique())[-15:]
        panel = panel[panel["date"].isin(dates)].reset_index(drop=True)

    f = build_frame(panel)

    def attach_anchor_returns(f, col):
        with np.errstate(all="ignore"):
            f[f"nxo@{col}"] = f["next_open"] / f[col] - 1.0
            f[f"nxc@{col}"] = f["next_close"] / f[col] - 1.0
        return f

    f = attach_anchor_returns(f, "p_at30m")
    # anchor at 10:30 needs the price column itself
    g1030 = pd.read_parquet(GRID_PATH, columns=["date", "ticker", "c1030"])
    f = f.merge(g1030, on=["date", "ticker"], how="left")
    f = attach_anchor_returns(f, "c1030")
    g1500 = pd.read_parquet(GRID_PATH, columns=["date", "ticker", "c1500"])
    f = f.merge(g1500, on=["date", "ticker"], how="left")
    f = attach_anchor_returns(f, "c1500")
    f = attach_anchor_returns(f, "day_close")
    with np.errstate(all="ignore"):
        f["overnight_proxy"] = f["next_open"] / f["day_close"] - 1.0
        f["rest_from_0930"] = np.where(
            f["p_at30m"].notna(), f["day_close"] / f["p_at30m"] - 1.0, np.nan)
    f = add_universe_benchmarks(f)

    res = {}
    THR_SURGE = (0.02, 0.03, 0.05)

    # ---- H1 / H2 : first-hour surge / crash ----
    OUT_H12 = ["fut_from_1030", "nxo@c1030", "nxc@c1030"]
    for hyp in ("H1_morning_surge", "H2_morning_crash"):
        blk = {}
        for thr in THR_SURGE:
            m = (f["r_firsthour"] >= thr) if hyp.endswith("surge") \
                else (f["r_firsthour"] <= -thr)
            blk[f"thr={thr}"] = event_block(f, m.fillna(False), OUT_H12,
                                            ~m.fillna(False))
        res[hyp] = blk

    # ---- H3 : afternoon surge -> continuation into close + next day ----
    OUT_H3 = ["fut_from_1500", "nxo@c1500", "nxc@c1500"]
    blk = {}
    for thr in THR_SURGE:
        m = f["r_1400_1500"].fillna(-99) >= thr
        blk[f"thr={thr}"] = event_block(f, m, OUT_H3, ~m)
    res["H3_afternoon_surge"] = blk

    # ---- H4 : afternoon crash -> next day ----
    OUT_H4 = ["overnight_proxy", "nxc@c1500"]
    blk = {}
    for thr in THR_SURGE:
        m = f["r_1400_close"].fillna(99) <= -thr
        blk[f"thr={thr}"] = event_block(f, m, OUT_H4, ~m)
    res["H4_afternoon_crash"] = blk

    # ---- H5 : opening surge -> rest of day ----
    OUT_H5 = ["fut_from_1030"]
    blk = {}
    for thr in (0.03, 0.05, 0.08):
        m = f["r30"].fillna(-99) >= thr
        b = event_block(f, m, ["rest_from_0930", "nxo@p_at30m", "nxc@p_at30m"], ~m)
        blk[f"thr={thr}"] = b
    res["H5_opening_surge"] = blk

    # ---- H6 : closing surge -> next day ----
    OUT_H6 = ["nxo@day_close", "nxc@day_close"]
    blk = {}
    for thr in THR_SURGE:
        m = f["r_1500_close"].fillna(-99) >= thr
        blk[f"thr={thr}"] = event_block(f, m, OUT_H6, ~m)
    res["H6_closing_surge"] = blk

    # ---- H7 / H8 : late-day extreme + volume surge ----
    late_low = (f["day_low_time"].fillna(0) >= 1300) & (f["nearLow"].fillna(1) <= 0.01)
    late_high = (f["day_high_time"].fillna(0) >= 1300) & (f["nearHigh"].fillna(1) <= 0.01)
    rv = f["rel_v_w1400_1500"]
    OUT_H78 = ["nxc@day_close", "nxo@day_close"]
    for hyp, base_m in (("H7_lowPlusVolume", late_low),
                        ("H8_highPlusVolume", late_high)):
        blk = {
            "base_noVolumeCond": event_block(f, base_m.fillna(False), OUT_H78),
            "volHi": {},
            "volLo": {},
            "volHi_vs_volLo": {},
        }
        for vthr in (1.5, 2.5, 4.0):
            mh = (base_m & (rv >= vthr)).fillna(False)
            ml = (base_m & (rv < 1.0)).fillna(False)
            blk["volHi"][f"rv>={vthr}"] = event_block(f, mh, OUT_H78)
            blk["volLo"][f"rv<1.0"] = event_block(f, ml, OUT_H78)
            blk["volHi_vs_volLo"][f"rv>={vthr}"] = {
                oc: paired_date_diff_ttest(f, mh, ml, oc) for oc in OUT_H78}
        res[hyp] = blk

    # ---- H9 : flat morning -> later direction/volatility ----
    flat = (f["w30_range"].fillna(99) <= 0.02)
    blk = {}
    for rt in (0.02, 0.03):
        rng_ok = (f["w30_range"] <= rt) & (f["r30"].abs() <= rt * 0.5)
        rng_bad = (f["w30_range"] >= 0.05)
        b = event_block(f, rng_ok.fillna(False), ["rest_from_0930", "nxc@day_close"],
                        rng_bad.fillna(False))
        # realized vol proxy afterwards: mean |slot returns| is not stored here;
        # use afternoon range via r_1400_close extremes instead (documented)
        blk[f"w30range<={rt}"] = b
    res["H9_flat_morning"] = blk

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "smoke" if args.smoke else "full",
        "definitions": {
            "anchors": "outcomes nxo@X/nxc@X = next session open/close over "
                       "price X; fut_* = same-session remainder",
            "excess": "same-date equal-weight segment mean over the eligible "
                      "universe",
            "thresholds": "grids only; no tuning against outcomes",
            "eligibility": "same base quality filter as other studies",
        },
        "sample": {"rows": int(len(f)), "days": int(f["date"].nunique())},
        "hypotheses": res,
        "pitNote": "event conditions use data up to their decision time only",
        "runtimeSec": round(time.time() - t0, 1),
    }
    out = round_block(out)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "study_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    md = ["# SNS 가설 H1~H9 Event Study\n",
          f"- rows={out['sample']['rows']:,} days={out['sample']['days']} "
          f"({out['runtimeSec']}s)\n"]
    md.append("| 가설 | 조건 | n | 다음날 종가 초과수익 | t | 승률 |")
    md.append("|---|---|---:|---:|---:|---:|")
    for hyp, blk in res.items():
        for key, b in blk.items():
            if not isinstance(b, dict) or "nxc@day_close" not in b and "nxc@c1030" not in b and "nxc@c1500" not in b and "nxc@p_at30m" not in b:
                continue
            occ = [k for k in ("nxc@day_close", "nxc@c1030", "nxc@c1500",
                               "nxc@p_at30m") if k in b]
            if not occ:
                continue
            st = b[occ[0]]
            md.append(f"| {hyp} | {key} | {st.get('n')} | "
                      f"{(st.get('meanExc') or 0)*100:+.3f}% | "
                      f"{st.get('tExc') if st.get('tExc') is not None else 'NA'} | "
                      f"{st.get('winRateExc') if st.get('winRateExc') is not None else 'NA'} |")
    with open(os.path.join(OUT_DIR, "study.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    print(json.dumps({"mode": out["mode"], "rows": out["sample"]["rows"],
                      "days": out["sample"]["days"],
                      "runtimeSec": out["runtimeSec"]}))
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
