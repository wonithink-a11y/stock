#!/usr/bin/env python
"""Time-of-day slot analysis (directive step 9).

Seven independent observation windows:
  09:00-09:30 / 09:30-10:30 / 10:30-11:30 / 11:30-13:00 /
  13:00-14:00 / 14:00-15:00 / 15:00-15:30

Per window features (all PIT-safe, from Stage-A caches):
  ret      : as-of close(end)/as-of close(start) - 1   [w1 uses open->0930]
  hi/lo    : max/min of bucket highs/lows within the window
  range    : (hi-lo)/window start price
  volume   : summed bucket share volume (+ relative vs trailing baseline)
  vwapDist : end price / window VWAP(amount/volume proxy) - 1

Research question: does the window's price shock predict the REST of the
day (window-end -> close) and the next session? Method = per-date quintile
assignment on each feature -> forward mean excess returns per quintile.

Usage: python run_timeofday.py [--smoke]
Writes findings/intraday-timeofday/{study_results.json,study.md}
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intraday import loader, market, session  # noqa: E402
from intraday.forward import build_next_day  # noqa: E402
from intraday.stats import rank_ic_by_date, round_block  # noqa: E402

SLAB = os.path.join(loader.REPO_ROOT, "research", "strategy-lab")
PANEL_PATH = os.path.join(SLAB, ".cache", "intraday_panel.parquet")
GRID_PATH = os.path.join(SLAB, ".cache", "intraday_grid5m.parquet")
OUT_DIR = os.path.join(SLAB, "findings", "intraday-timeofday")

WINDOWS = (
    ("w0900_0930", 900, 930),
    ("w0930_1030", 930, 1030),
    ("w1030_1130", 1030, 1130),
    ("w1130_1300", 1130, 1300),
    ("w1300_1400", 1300, 1400),
    ("w1400_1500", 1400, 1500),
    ("w1500_1530", 1500, 1530),
)


def load_grid():
    marks = [int(m) for m in session.GRID_MARKS]
    cols = ["date", "ticker"]
    for m in marks:
        cols += [f"c{m:04d}", f"v{m:04d}", f"h{m:04d}", f"l{m:04d}", f"a{m:04d}"]
    return pd.read_parquet(GRID_PATH, columns=cols), marks


def build_slot_features(panel, grid, marks):
    """Wide grid -> one row per ticker-day with per-window features.

    REQUIRES grid already restricted/sorted to match panel rows 1:1
    (same (date,ticker) order)."""
    mark_pos = {int(m): k for k, m in enumerate(marks)}
    out = panel[["date", "ticker", "market", "open_price", "p_at30m",
                 "day_close", "r30"]].copy()

    for label, s, e in WINDOWS[1:]:
        ks = [mark_pos[m] for m in marks if s < int(m) <= e]
        # start price = as-of close at the window's START mark
        c_start_col = f"c{s:04d}"
        c_end_col = f"c{e:04d}"
        with np.errstate(all="ignore"):
            sp = grid[c_start_col].to_numpy(dtype=float)
            ep = grid[c_end_col].to_numpy(dtype=float)
            out[f"ret_{label}"] = np.where(sp > 0, ep / sp - 1.0, np.nan)
            hi = grid[[f"h{marks[k]:04d}" for k in ks]].max(axis=1).to_numpy(dtype=float)
            lo = grid[[f"l{marks[k]:04d}" for k in ks]].min(axis=1).to_numpy(dtype=float)
            rng_ok = (hi >= lo) & (sp > 0) & (hi > lo)
            out[f"range_{label}"] = np.where(rng_ok, (hi - lo) / sp, np.nan)
        vcols = [f"v{marks[k]:04d}" for k in ks]
        acols = [f"a{marks[k]:04d}" for k in ks]
        vol = grid[vcols].sum(axis=1, min_count=1)
        amt = grid[acols].sum(axis=1, min_count=1)
        out[f"vol_{label}"] = vol.to_numpy()
        with np.errstate(all="ignore"):
            vwap = amt / vol.replace(0, np.nan)
            out[f"vwapDist_{label}"] = np.where(vol > 0, ep / vwap - 1.0, np.nan)
        # relative volume: trailing baselines already exist in the panel
        base_col = f"rel_v_{label}"
        if base_col in panel.columns:
            out[f"relVol_{label}"] = panel[base_col].to_numpy()

    # window 1 = OPEN30 itself
    out["ret_w0900_0930"] = out["r30"]
    out["range_w0900_0930"] = panel["w30_range"].to_numpy()
    out["vol_w0900_0930"] = panel["w_vol"].to_numpy()
    if "rel_w_amt" in panel.columns:
        out["relVol_w0900_0930"] = panel["rel_w_amt"].to_numpy()
    with np.errstate(all="ignore"):
        wv = panel["w_vol"].to_numpy(dtype=float)
        vwap30 = panel["w_amt"].to_numpy(dtype=float) / \
            np.where(wv > 0, wv, np.nan)
        out["vwapDist_w0900_0930"] = np.where(
            np.isfinite(vwap30) & (vwap30 > 0),
            panel["p_at30m"].to_numpy(dtype=float) / vwap30 - 1.0, np.nan)
    out["day_vol"] = panel["day_vol"].to_numpy()

    # future outcomes measured from the window END price:
    #   futEnd_* = window-end -> day close ; futNxt_* = window-end -> next close
    nd = build_next_day(panel)
    out = out.merge(nd, on=["ticker", "date"], how="left")
    close = out["day_close"].to_numpy(dtype=float)
    nxt_close = out.get("next_close", pd.Series(np.nan, index=out.index)).to_numpy(dtype=float)
    for label, s, e in WINDOWS:
        pend = out["p_at30m"] if e == 930 else grid[f"c{e:04d}"]
        with np.errstate(all="ignore"):
            pe = pend.to_numpy(dtype=float)
            out[f"futEnd_{label}"] = np.where(pe > 0, close / pe - 1.0, np.nan)
            out[f"futNxt_{label}"] = np.where(pe > 0, nxt_close / pe - 1.0, np.nan)
    return out


def quintile_table(df, feat, fwd_cols, q=5):
    """Per-date quintiles of feat -> per-quintile mean excess of fwd_cols."""
    d = df.dropna(subset=[feat]).copy()
    if len(d) < 500:
        return None
    d["_q"] = d.groupby("date")[feat].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * q), q))
    res = {}
    for fc in fwd_cols:
        exc_name = fc + "_exc"
        if exc_name not in d.columns:
            m = d.dropna(subset=[fc]).groupby(["date", "market"])[fc].transform("mean")
            d[exc_name] = d[fc] - m
        g = d.groupby("_q")[exc_name].agg(["mean", "count",
                                           lambda s: (s > 0).mean()])
        g.columns = ["meanExc", "n", "winRate"]
        res[fc] = {f"Q{k}": {"meanExc": float(g.loc[k, "meanExc"]),
                             "n": int(g.loc[k, "n"]),
                             "winRate": float(g.loc[k, "winRate"])}
                   for k in g.index}
        top_bot = g.loc[q, "meanExc"] - g.loc[1, "meanExc"]
        res[fc]["Q5minusQ1"] = float(top_bot)
    res["_featureICs"] = {
        fc: rank_ic_by_date(d, feat, fc) for fc in fwd_cols}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    panel = pd.read_parquet(PANEL_PATH)
    ok = ((panel["n_bars_day"] >= 20) & (panel["day_open"] > 0) &
          (panel["day_close"] > 0) & (panel["day_high"] >= panel["day_low"]) &
          (panel["day_ret_oc"].abs() <= 0.315) & panel["market"].notna())
    panel = panel[ok].reset_index(drop=True)
    if args.smoke:
        dates = sorted(panel["date"].unique())[-15:]
        panel = panel[panel["date"].isin(dates)].reset_index(drop=True)

    grid, marks = load_grid()
    # align grid 1:1 with the filtered panel rows (same key order)
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)
    grid = (grid.merge(panel[["date", "ticker"]], on=["date", "ticker"],
                       how="inner")
                .sort_values(["date", "ticker"]).reset_index(drop=True))
    if len(grid) != len(panel):
        raise RuntimeError(f"grid/panel key mismatch {len(grid)} vs {len(panel)}")
    sf = build_slot_features(panel, grid, marks)

    profile = {}
    for label, s, e in WINDOWS:
        r = sf[f"ret_{label}"]
        wv_sum = sf.groupby("date")[f"vol_{label}"].transform("sum")
        day_sum = sf.groupby("date")["day_vol"].transform("sum")
        row = {
            "meanAbsRet": float(r.abs().mean()),
            "posShare": float((r > 0).mean()),
            "medianRange": float(sf[f"range_{label}"].median()),
            "volumeShareOfDay": float((wv_sum / day_sum.replace(0, np.nan)).mean()),
        }
        vd = sf.get(f"vwapDist_{label}")
        if vd is not None:
            row["medianVwapDist"] = float(vd.median())
        profile[label] = row

    results = {}
    for label, _, _ in WINDOWS:
        feats = [c for c in (f"ret_{label}", f"range_{label}",
                             f"relVol_{label}", f"vwapDist_{label}")
                 if c in sf.columns and sf[c].notna().sum() > 1000]
        blk = {}
        # rest-of-day after this window ends + next session
        fut = [f"futEnd_{label}", f"futNxt_{label}"]
        for feat in feats:
            blk[feat] = quintile_table(sf, feat, fut)
        results[label] = blk

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "smoke" if args.smoke else "full",
        "definitions": {
            "windows": {l: f"{s}-{e}" for l, s, e in WINDOWS},
            "ret": "as-of close(end)/as-of close(start)-1; w1 = open->0930",
            "range": "(hi-lo)/start price using bucket h/l inside window",
            "relVol": "window volume / trailing expanding mean shifted 1 "
                      "session (same window, min_periods=5)",
            "vwapDist": "end as-of close / window VWAP(close*vol proxy)-1",
            "quintiles": "per-date rank(method='first') quintiles of feature",
            "outcomes": "futEnd_* = window-end -> day close excess; "
                        "futNxt_* = window-end -> next close excess "
                        "(benchmark = same-date EW segment mean)",
        },
        "sample": {"rows": int(len(sf)), "days": int(sf["date"].nunique())},
        "profile": profile,
        "results": results,
        "runtimeSec": round(time.time() - t0, 1),
    }
    out = round_block(out)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "study_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    md = ["# 시간대별 Intraday 분석 (step 9)\n",
          f"- rows={out['sample']['rows']:,}, days={out['sample']['days']}, "
          f"mode={out['mode']}"]
    md.append("\n## 창 프로파일\n")
    md.append("| 창 | |ret|평균 | 양방향비중 | 중앙range | 거래량비중(일중) |")
    md.append("|---|---:|---:|---:|---:|")
    for l, pr in profile.items():
        md.append(f"| {l} | {pr['meanAbsRet']*100:.3f}% | "
                  f"{pr['posShare']*100:.1f}% | {pr['medianRange']*100:.2f}% | "
                  f"{pr['volumeShareOfDay']*100:.1f}% |")
    md.append("\n## 창 수익률 5분위 -> 잔여 당일(futEnd) 초과수익 Q5-Q1\n")
    md.append("| 창 | Q5-Q1 | IC(mean,t) |")
    md.append("|---|---:|---|")
    for l, blk in results.items():
        ft = blk.get(f"ret_{l}")
        if not ft:
            continue
        for fc in ("futEnd_" + l, "futNxt_" + l):
            t = ft.get(fc)
            ic = ft.get("_featureICs", {}).get(fc, {})
            if t and t.get("Q5minusQ1") is not None:
                mic = ic.get("meanIC"); tic = ic.get("tIC")
                md.append(f"| {l[:9]}→{fc[3:9]} | {t['Q5minusQ1']*100:+.3f}% | "
                          f"{mic if mic is not None else float('nan'):+.4f}, "
                          f"{tic if tic is not None else float('nan'):+.2f} |")
    with open(os.path.join(OUT_DIR, "study.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    print(json.dumps({"mode": out["mode"], "rows": out["sample"]["rows"],
                      "days": out["sample"]["days"],
                      "runtimeSec": out["runtimeSec"]}))
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
