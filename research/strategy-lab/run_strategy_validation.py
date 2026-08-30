#!/usr/bin/env python
"""Strategy-candidate validation pipeline (directive steps 16-22).

Candidates come from the event studies - only hypotheses whose effect
survived multiple thresholds and splits are simulated as rules:

  CAND1 PMCRASH_REVERSAL : r(14:00->close) <= -thr  -> buy NEXT OPEN,
        exit next session @ {0935,1030,close}; optional volume filter
        (rel_v_w1400_1500 < vthr) and market filter (KOSPI-EW ret <= mthr)
  CAND2 OPEN30_FADE      : r30 in the date's bottom q% -> buy at 09:30
        as-of price, exit day close (same-session reversion)
  CAND3 LAST30_OVERNIGHT : r(15:00->close) <= -thr -> buy close, sell next
        open (pure overnight)

Protocol:
  - Time split 60/15/25% of the 250 sessions: TRAIN / VALID / TEST.
    Parameter sweep runs on TRAIN ONLY; the chosen config is frozen and
    reported on VALID and TEST.
  - Costs: round-trip bps grid {0, 10, 20, 40} applied to every trade.
  - Baselines: universe EW over the SAME window, random entries matched to
    daily signal counts (seeded), and the naive "below open at 09:30" rule.
  - Portfolio: equal-weight across the day's signals, cash otherwise.
  - Metrics: research/strategy-lab/engine/metrics/metrics.py (reused).

Usage: python run_strategy_validation.py [--smoke]
Writes findings/strategy-candidates/{study_results.json,study.md}
"""
import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
SLAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SLAB)
from intraday import loader, market, session  # noqa: E402
from intraday.stats import round_block  # noqa: E402
from engine.metrics import metrics as em  # noqa: E402

PANEL_PATH = os.path.join(SLAB, ".cache", "intraday_panel.parquet")
GRID_PATH = os.path.join(SLAB, ".cache", "intraday_grid5m.parquet")
OUT_DIR = os.path.join(SLAB, "findings", "strategy-candidates")

COST_GRID = (0.0, 10.0, 20.0, 40.0)   # round-trip bps


def load_frame():
    panel = pd.read_parquet(PANEL_PATH)
    ok = ((panel["n_bars_day"] >= 50) & (panel["day_open"] > 0) &
          (panel["day_close"] > 0) & (panel["day_high"] >= panel["day_low"]) &
          (panel["day_ret_oc"].abs() <= 0.315) &
          (panel["r30"].abs() <= 0.30) & panel["market"].notna())
    p = panel[ok].reset_index(drop=True)
    p = p.sort_values(["date", "ticker"]).reset_index(drop=True)
    marks_needed = (935, 1030, 1400, 1500, 1530)
    cols = ["date", "ticker"] + [f"c{m:04d}" for m in marks_needed]
    g = pd.read_parquet(GRID_PATH, columns=cols)
    g = (g.merge(p[["date", "ticker"]], on=["date", "ticker"], how="inner")
          .sort_values(["date", "ticker"]).reset_index(drop=True))
    assert len(g) == len(p)

    f = p[["date", "ticker", "market", "liq_decile", "open_price",
           "p_at30m", "day_close", "r30", "w30_range",
           "rel_v_w1400_1500"]].copy()
    regimes = market.day_regimes(p)
    f = market.attach_regimes(f, regimes)

    with np.errstate(all="ignore"):
        c14 = g["c1400"].to_numpy(float)
        c15 = g["c1500"].to_numpy(float)
        c1530 = g["c1530"].to_numpy(float)
        f["r_1400_close"] = np.where(c14 > 0, c1530 / c14 - 1.0, np.nan)
        f["r_1500_close"] = np.where(c15 > 0, c1530 / c15 - 1.0, np.nan)
        f["px_c0935"] = g["c0935"].to_numpy(float)
        f["px_c1030"] = g["c1030"].to_numpy(float)

    # next-session prices via adjacency on TICKER-sorted rows
    ps = pd.DataFrame({
        "ticker": p["ticker"].to_numpy(), "date": p["date"].to_numpy(),
        "day_open": p["day_open"].to_numpy(),
        "day_close": p["day_close"].to_numpy(),
        "g_c0935": g["c0935"].to_numpy(float),
        "g_c1030": g["c1030"].to_numpy(float),
    }).sort_values(["ticker", "date"]).reset_index(drop=True)
    tks = ps["ticker"].to_numpy()
    same = np.empty(len(tks), dtype=bool)
    same[:-1] = tks[:-1] == tks[1:]
    same[-1] = False
    idx = np.where(same)[0]
    nxt = pd.DataFrame({
        "ticker": tks[idx],
        "date": ps["date"].to_numpy()[idx],           # signal session
        "n_open": ps["day_open"].to_numpy()[idx + 1],
        "n_close": ps["day_close"].to_numpy()[idx + 1],
        "n_c0935": ps["g_c0935"].to_numpy()[idx + 1],
        "n_c1030": ps["g_c1030"].to_numpy()[idx + 1],
    })
    f = f.merge(nxt, on=["ticker", "date"], how="left")
    return f, p, g


def daily_series(f, mask, entry_col, exit_col, cost_bps):
    """Equal-weight daily portfolio return over signaled rows (NaN exits
    excluded); returns Series indexed by date (cash=0 days included later)."""
    sub = f[mask.reindex(f.index).fillna(False)]
    with np.errstate(all="ignore"):
        gross = sub[exit_col] / sub[entry_col] - 1.0 - cost_bps / 1e4
    daily = gross.dropna().groupby(sub["date"]).mean()
    daily.name = "strat"
    return daily


def bench_daily(f, entry_col, exit_col):
    """Universe EW over the identical window."""
    with np.errstate(all="ignore"):
        r = f[exit_col] / f[entry_col] - 1.0
    return r.dropna().groupby(f["date"]).mean()


def random_control(f, mask, entry_col, exit_col, cost_bps, seed=7):
    rng = np.random.default_rng(seed)
    counts = mask.groupby(f["date"]).sum()
    out = {}
    for d, n in counts.items():
        if n <= 0:
            continue
        day = f[f["date"] == d]
        pick = day.iloc[rng.choice(len(day), size=int(min(n, len(day))),
                                   replace=False)]
        with np.errstate(all="ignore"):
            r = pick[exit_col] / pick[entry_col] - 1.0 - cost_bps / 1e4
        out[d] = float(r.dropna().mean())
    return pd.Series(out, name="rand")


def equity_metrics(daily, dates_all):
    """Full-sample equity curve incl. cash days -> engine metrics dict."""
    s = daily.reindex(dates_all).fillna(0.0)
    eq = (1.0 + s).cumprod()
    curve = list(zip(s.index, eq.to_numpy()))
    return {
        "totalReturn": em.total_return(curve),
        "cagr": em.cagr(curve),
        "mdd": em.max_drawdown(curve),
        "sharpe": em.sharpe(curve),
        "sortino": em.sortino(curve),
    }


def excess_stats(daily_strat, daily_bench):
    j = pd.concat([daily_strat, daily_bench], axis=1, join="inner").dropna()
    if len(j) < 10:
        return {"nDays": int(len(j)), "meanExcess": None, "t": None}
    d = j.iloc[:, 0] - j.iloc[:, 1]
    t = d.mean() / (d.std(ddof=1) / len(d) ** 0.5)
    from scipy import stats as sps
    pv = float(sps.ttest_1samp(d.to_numpy(), 0.0)[1])
    return {"nDays": int(len(j)), "meanExcess": float(d.mean()),
            "t": float(t), "p": pv}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    f, p, _g = load_frame()
    dates = sorted(f["date"].unique())
    if args.smoke:
        dates = dates[-30:]
        f = f[f["date"].isin(dates)].reset_index(drop=True)
    n = len(dates)
    i_tr, i_va = int(n * 0.60), int(n * 0.75)
    tr_dates = set(dates[:i_tr])
    va_dates = set(dates[i_tr:i_va])
    te_dates = set(dates[i_va:])
    print(f"sessions={n} train={len(tr_dates)} valid={len(va_dates)} test={len(te_dates)}")

    kr = f["reg_kospi_ret"]
    rv = f["rel_v_w1400_1500"]

    # ---------------- candidate signal definitions ------------------------
    def sig_pmcrash(thr, vthr=None, mthr=None):
        m = f["r_1400_close"] <= -thr
        if vthr is not None:
            m &= rv < vthr
        if mthr is not None:
            m &= kr <= mthr
        return m.fillna(False)

    def sig_open30_fade(q=0.10):
        rk = f.groupby("date")["r30"].rank(pct=True)
        return (rk <= q).fillna(False)

    def sig_last30(thr):
        return (f["r_1500_close"] <= -thr).fillna(False)

    candidates = {
        "CAND1_pmcrash": {
            "grid": [dict(thr=t, vthr=v, mthr=m, exit=e)
                     for t in (0.02, 0.03, 0.05, 0.07)
                     for v in (None, 1.0, 1.5)
                     for m in (None, -0.01)
                     for e in ("n_c0935", "n_c1030", "n_close")],
            "entry": "n_open", "bench": ("n_open", None),
        },
        "CAND2_open30fade": {
            "grid": [dict(exit="day_close")],
            "entry": "p_at30m",
        },
        "CAND3_last30overnight": {
            "grid": [dict(thr=t) for t in (0.02, 0.03, 0.05)],
            "entry": "day_close", "bench": ("n_open", None),
        },
    }

    results = {"splits": {"train": sorted(tr_dates)[-1], "valid": sorted(va_dates)[0],
                          "test": sorted(te_dates)[0]},
               "candidates": {}}

    # ---------------- CAND1 sweep (TRAIN ONLY) ----------------------------
    cand1 = []
    for prm in candidates["CAND1_pmcrash"]["grid"]:
        mask = sig_pmcrash(prm["thr"], prm["vthr"], prm["mthr"])
        ntr = int((mask & f["date"].isin(tr_dates)).sum())
        if ntr < 200:
            continue
        d = daily_series(f, mask, "n_open", prm["exit"], cost_bps=0.0)
        b = bench_daily(f, "n_open", prm["exit"])
        ex = excess_stats(d[d.index.isin(tr_dates)], b[b.index.isin(tr_dates)])
        cand1.append({**prm, "trainN": ntr, "trainMeanExc": ex["meanExcess"],
                      "trainT": ex["t"]})
    cand1 = [c for c in cand1 if c["trainMeanExc"] is not None]
    cand1.sort(key=lambda c: -(c["trainT"] or -9))
    best1 = cand1[0] if cand1 else None

    # ---------------- evaluate frozen configs on all splits ---------------
    def eval_config(name, mask, entry, exit_col):
        blk = {"nTotal": int(mask.sum())}
        d_all = {}
        for cost in COST_GRID:
            d = daily_series(f, mask, entry, exit_col, cost)
            d_all[cost] = d
            blk[f"cost{cost:.0f}bps"] = {}
            for split_name, dset in (("train", tr_dates), ("valid", va_dates),
                                     ("test", te_dates)):
                dd = d[d.index.isin(dset)]
                b = bench_daily(f, entry, exit_col)
                ex = excess_stats(dd, b[b.index.isin(dset)])
                eq = equity_metrics(dd, sorted(dset))
                blk[f"cost{cost:.0f}bps"][split_name] = {
                    "nDays": ex["nDays"],
                    "meanExcess": ex["meanExcess"], "excessT": ex["t"],
                    "totalReturn": eq["totalReturn"], "cagr": eq["cagr"],
                    "sharpe": eq["sharpe"], "mdd": eq["mdd"],
                }
        # random control at 20bps for context
        d20 = d_all[20.0]
        rc = random_control(f, mask, entry, exit_col, 20.0)
        blk["randomControl20bps_meanDaily"] = float(rc.mean()) if len(rc) else None
        blk["strat20bps_meanDaily"] = float(d20.mean()) if len(d20) else None
        return blk

    if best1 is not None:
        mask1 = sig_pmcrash(best1["thr"], best1["vthr"], best1["mthr"])
        results["candidates"]["CAND1_pmcrash"] = {
            "chosenParams": best1, "eval": eval_config(
                "CAND1", mask1, "n_open", best1["exit"])}
        # robustness around the chosen config
        rb = {}
        for t in {best1["thr"], max(0.01, best1["thr"] - 0.01),
                  best1["thr"] + 0.01}:
            for e in ("n_c0935", "n_c1030"):
                m2 = sig_pmcrash(t, best1["vthr"], best1["mthr"])
                d = daily_series(f, m2, "n_open", e, 20.0)
                b = bench_daily(f, "n_open", e)
                ex = excess_stats(d, b)
                rb[f"thr={t}|exit={e}"] = {"meanExcessAll": ex["meanExcess"],
                                           "t": ex["t"]}
        for seg_name, seg_mask in (("KOSPI", f["market"] == "KOSPI"),
                                   ("KOSDAQ", f["market"] == "KOSDAQ"),
                                   ("liquidD8-10", f["liq_decile"] >= 8),
                                   ("illiquidD1-3", f["liq_decile"] <= 3)):
            m3 = mask1 & seg_mask.fillna(False)
            d = daily_series(f, m3, "n_open", best1["exit"], 20.0)
            # benchmark stays the WHOLE universe over the same window
            b = bench_daily(f, "n_open", best1["exit"])
            ex = excess_stats(d, b)
            rb[seg_name] = {"meanExcess": ex["meanExcess"], "t": ex["t"],
                            "nDays": ex["nDays"]}
        results["candidates"]["CAND1_pmcrash"]["robustness"] = rb

    mask2 = sig_open30_fade()
    results["candidates"]["CAND2_open30fade"] = {
        "params": {"bottomQ": 0.10},
        "eval": eval_config("CAND2", mask2, "p_at30m", "day_close")}

    for t in (0.02, 0.03, 0.05):
        m3 = sig_last30(t)
        key = f"CAND3_last30_thr{int(t*100)}pct"
        results["candidates"][key] = {
            "eval": eval_config(key, m3, "day_close", "n_open")}

    results.update({
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "smoke" if args.smoke else "full",
        "protocol": {
            "split": "60/15/25 sessions time-ordered",
            "costsBpsRT": list(COST_GRID),
            "portfolio": "equal-weight across day signals, cash otherwise",
            "pit": "signals use data <= decision time; entry strictly after",
            "paramSelection": "TRAIN split only (CAND1 grid); others fixed a-priori",
        },
        "runtimeSec": round(time.time() - t0, 1)})
    out = round_block(results)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "study_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    # ---- markdown summary ----
    md = ["# 전략 후보 검증 (steps 16-22)\n",
          f"sessions: train<= {out['splits']['train']} / valid from "
          f"{out['splits']['valid']} / test from {sorted(te_dates)[0]}\n"]
    for cname, cb in results["candidates"].items():
        ev = cb.get("eval") or cb
        md.append(f"\n## {cname}")
        if "chosenParams" in cb:
            md.append(f"- chosen(train): {cb['chosenParams']}")
        hdr = "| 비용 | 구간 | 초과수익/일 | t | CAGR | MDD | Sharpe |"
        md.append(hdr)
        md.append("|---|---|---:|---:|---:|---:|---:|")
        for ck, cv in ev.items():
            if not ck.startswith("cost"):
                continue
            for split in ("train", "valid", "test"):
                s = cv.get(split) or {}
                if not s:
                    continue
                me = s.get("meanExcess")
                md.append(f"| {ck} | {split} | "
                          f"{(me*100 if me is not None else float('nan')):+.3f}% | "
                          f"{s.get('excessT') if s.get('excessT') is not None else float('nan'):+.2f} | "
                          f"{(s.get('cagr') if s.get('cagr') is not None else float('nan'))*100:+.1f}% | "
                          f"{(s.get('mdd') if s.get('mdd') is not None else float('nan'))*100:.1f}% | "
                          f"{s.get('sharpe') if s.get('sharpe') is not None else float('nan'):+.2f} |")
        if "robustness" in cb:
            md.append("- robustness: " + json.dumps(
                {k: (round(v['meanExcess'] * 100, 3) if v.get('meanExcess') is not None else None)
                 for k, v in cb["robustness"].items()}, ensure_ascii=False))
    with open(os.path.join(OUT_DIR, "study.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    print(json.dumps({"mode": out["mode"], "runtimeSec": out["runtimeSec"],
                      "cands": list(results["candidates"].keys())}))
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
