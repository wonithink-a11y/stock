#!/usr/bin/env python
"""OPEN30 pattern event study (directive steps 4-7).

Research question: after the first 30 minutes of KRX regular trading, do the
five OPEN30 path patterns predict same-session / next-session returns better
than the naive "is price above the open at 09:30?" rule?

Data: Stage-A caches (.cache/intraday_panel.parquet + intraday_grid5m.parquet)
built from the local minute_raw mirror (252 sessions 2025-08-08..2026-08-21).
Definitions inherit build_intraday_panel.py + intraday/patterns.py.

PIT: features use bars <= 09:30 only; everything later exists only as
forward returns. Market-adjusted return subtracts the same-date equal-weight
segment mean computed over the SAME eligible base (no look-ahead: the
benchmark is a contemporaneous cross-section).

Usage:
  python run_open30_study.py            # full sample
  python run_open30_study.py --smoke   # last 20 sessions only
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
from intraday import loader, market, patterns  # noqa: E402
from intraday.forward import build_next_day, forward_returns  # noqa: E402
from intraday.stats import rank_ic_by_date, round_block, summarize  # noqa: E402

SLAB = os.path.join(loader.REPO_ROOT, "research", "strategy-lab")
PANEL_PATH = os.path.join(SLAB, ".cache", "intraday_panel.parquet")
GRID_PATH = os.path.join(SLAB, ".cache", "intraday_grid5m.parquet")
OUT_DIR = os.path.join(SLAB, "findings", "open30-event-study")

DEFAULT_THR = 0.005
THR_GRID = (0.003, 0.005, 0.01, 0.02)

EVENT_MARK = 930          # decision point hhmm
PRICE_COL = "p_at30m"

OUTCOMES = ("f005", "f010", "f030", "f060", "f120",
            "f_dayclose", "r_next_close", "r_next_open", "overnight")


def load_grid_closes():
    cols = ["date", "ticker"] + [f"c{m:04d}" for m in range(905, 1531, 5)]
    return pd.read_parquet(GRID_PATH, columns=cols)


def base_eligible(panel):
    """Quality + freshness + limit-breach filter (quality report R7/R5)."""
    ok = (
        (panel["n_bars_30"] >= 20)
        & (panel["last_bar_30"] >= 925)
        & (panel["open_price"] > 0)
        & (panel["p_at30m"] > 0)
        & (panel["w_high"] >= panel["w_low"])
        & (panel["r30"].abs() <= 0.30)
        & (panel["day_ret_oc"].abs() <= 0.315)
        & panel["market"].notna()
    )
    return panel[ok].copy()


def paired_date_diff_ttest(ev, mask_a, mask_b, col, min_per_day=3):
    """Per-date mean(A)-mean(B) differences -> one-sample t-test over dates."""
    a = ev[mask_a].groupby("date")[col].mean()
    b = ev[mask_b].groupby("date")[col].mean()
    d = (a - b).dropna()
    d = d[a.reindex(d.index).notna() & b.reindex(d.index).notna()]
    counts_ok = True
    if len(d) < 10:
        return {"nDates": int(len(d)), "meanDiff": None, "t": None}
    t, p = sps.ttest_1samp(d.to_numpy(), 0.0)
    return {"nDates": int(len(d)),
            "meanDiff": float(np.mean(d)),
            "t": float(t), "p": float(p),
            "positiveDayShare": float((d > 0).mean())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    panel = pd.read_parquet(PANEL_PATH)
    if args.smoke:
        dates = sorted(panel["date"].unique())[-20:]
        panel = panel[panel["date"].isin(dates)]
    base = base_eligible(panel)
    print(f"base rows={len(base):,} days={base['date'].nunique()}")

    grid_closes = load_grid_closes()
    next_day = build_next_day(base)

    # ---- events = every eligible ticker-day; decision at 09:30 ----
    ev = base[["date", "ticker", "market", "sector", "open_price",
               PRICE_COL, "day_close", "r30", "w30_range", "range_position",
               "w_high", "w_low",
               "w_high_time", "w_low_time", "hi_before_lo",
               "rel_w_amt", "liq_decile", "day_amt"]].copy()
    ev["event_mark"] = EVENT_MARK
    ev = forward_returns(ev, grid_closes, next_day, price_col=PRICE_COL)

    # market-adjusted outcomes (benchmark = eligible-universe EW per date x segment)
    ev = market.add_excess(ev, [c for c in OUTCOMES])

    # classifications at default + sweep thresholds
    ev["pattern"] = patterns.classify_open30(ev, thr_up=DEFAULT_THR)
    ev["baseline"] = patterns.classify_simple_baseline(ev)
    cnt = {str(t): patterns.classify_open30(ev, thr_up=t).value_counts().to_dict()
           for t in THR_GRID}

    # ---- headline stats: pattern x outcome ----
    results = {}
    for grp_col, key in (("pattern", "patterns"), ("baseline", "baseline")):
        block = {}
        for g, sub in ev.groupby(grp_col):
            if g is None:
                continue
            block[g] = {h: summarize(sub[h], sub.get(f"{h}_exc")) for h in OUTCOMES}
        results[key] = block

    # ---- rank IC: r30 vs outcomes (continuous baseline strength) ----
    ric = {}
    for h in OUTCOMES:
        ric[h] = rank_ic_by_date(ev, "r30", h)

    # ---- directive-mandated comparisons ----
    pats = ev["pattern"]
    comps = {
        "RECOVER_OPEN_vs_FAILED_RECOVERY": {},
        "HOLD_ABOVE_OPEN_vs_FAILED_UP": {},
        "withinAbove_HOLD_vs_RECOVER": {},
        "withinBelow_FAILED_RECOVERY_vs_FAILED_UP": {},
        "simpleBaseline_above_minus_below": {},
    }
    for h in ("f010", "f060", "f120", "f_dayclose", "r_next_close"):
        comps["RECOVER_OPEN_vs_FAILED_RECOVERY"][h] = paired_date_diff_ttest(
            ev, pats == "RECOVER_OPEN", pats == "FAILED_RECOVERY", h)
        comps["HOLD_ABOVE_OPEN_vs_FAILED_UP"][h] = paired_date_diff_ttest(
            ev, pats == "HOLD_ABOVE_OPEN", pats == "FAILED_UP", h)
        comps["withinAbove_HOLD_vs_RECOVER"][h] = paired_date_diff_ttest(
            ev, pats == "HOLD_ABOVE_OPEN", pats == "RECOVER_OPEN", h)
        comps["withinBelow_FAILED_RECOVERY_vs_FAILED_UP"][h] = paired_date_diff_ttest(
            ev, pats == "FAILED_RECOVERY", pats == "FAILED_UP", h)
        bl = ev["baseline"]
        comps["simpleBaseline_above_minus_below"][h] = paired_date_diff_ttest(
            ev, bl == "SIMPLE_ABOVE_OPEN", bl == "SIMPLE_BELOW_OPEN", h)

    # ---- regime splits on two key horizons ----
    regimes_df = market.day_regimes(base)
    ev = market.attach_regimes(ev, regimes_df)
    masks = market.regime_masks(ev)
    reg_block = {}
    for g, sub in ev.groupby("pattern"):
        reg_block[g] = {}
        for mname, m in masks.items():
            s2 = sub[m.reindex(sub.index)]
            row = {}
            for h in ("f_dayclose", "r_next_close"):
                st = summarize(s2[h], s2.get(f"{h}_exc"))
                row[h] = {"n": st["n"], "meanExc": st["excess"]["meanExcess"]
                          if st.get("excess") else None,
                          "winRate": st["winRate"]}
            reg_block[g][mname] = row

    # ---- threshold sensitivity on key horizons ----
    sens = {}
    for t in THR_GRID:
        lab = patterns.classify_open30(ev, thr_up=t)
        row = {}
        for g in patterns.PATTERNS:
            s2 = ev[lab == g]
            rr = {}
            for h in ("f_dayclose", "r_next_close"):
                st = summarize(s2[h], s2.get(f"{h}_exc"))
                rr[h] = {"n": st["n"], "meanExc": st["excess"]["meanExcess"]
                         if st.get("excess") else None}
            row[g] = rr
        sens[str(t)] = row

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "smoke" if args.smoke else "full",
        "dataSources": [
            ".cache/intraday_panel.parquet (Stage-A, minute_raw mirror)",
            ".cache/intraday_grid5m.parquet (as-of 5m close grid)",
        ],
        "definitions": {
            "window": "formation bars 0900..0929; decision = as-of close @0930",
            "patterns": patterns.__doc__.strip().split("Deterministic")[0]
                        .split("Definitions")[1].strip(),
            "precedenceNote": "wide-range windows: dn_move tested before "
                              "up_move (documented convention)",
            "thresholdsDefault": {"thrUp": DEFAULT_THR, "thrDown": DEFAULT_THR},
            "outcomes": "f### same-session from as-of grid closes; "
                        "r_next_* from next session panel rows; overnight = "
                        "next_open/day_close",
            "benchmark": "same-date equal-weight eligible-universe mean per "
                         "market segment (V1~V9 convention)",
            "eligibility": "n_bars_30>=20 & last_bar_30>=925 & prices>0 & "
                           "|r30|<=30% & |oc|<=31.5% & market known",
        },
        "sample": {
            "events": int(len(ev)), "days": int(ev["date"].nunique()),
            "tickers": int(ev["ticker"].nunique()),
            "patternCountsDefault":
                ev["pattern"].value_counts().to_dict(),
            "patternCountsByThreshold": cnt,
        },
        "results": results,
        "rankIC_r30_vs_outcome": ric,
        "comparisons": comps,
        "regimes": reg_block,
        "thresholdSensitivity": sens,
        "pitNote": "features use data <= 09:30 only; forward returns and "
                   "benchmarks start at/after 09:30",
        "runtimeSec": round(time.time() - t0, 1),
    }
    out = round_block(out)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "study_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(json.dumps({
        "mode": out["mode"], "events": out["sample"]["events"],
        "days": out["sample"]["days"], "runtimeSec": out["runtimeSec"],
        "counts": out["sample"]["patternCountsDefault"],
    }, ensure_ascii=False))
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
