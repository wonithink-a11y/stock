#!/usr/bin/env python
"""Support/resistance level breaks + stop-loss study (directive step 13, H10).

Levels are QUANTITATIVE only - prior-session rolling windows from the panel
(shift(1), PIT-safe):
    lo_l5 / hi_l5   : rolling 5-session day low/high
    lo_l20 / hi_l20 : rolling 20-session day low/high

Events (first grid close crossing the level intraday):
  SUP_BREAK_n : close < lo_ln   ("지지선 이탈")
  RES_BREAK_n : close > hi_ln

Outcomes measured FROM THE BREAK PRICE at the break mark: +5/+30/+60/+120m,
day close, next open/close.

Stop-loss question split exactly as the directive asks:
  - 손절이 MDD를 얼마나 줄이는가 : MAE distribution after the break
  - 손절 후 반등을 얼마나 놓치는가: share of events where holding to close
    beat the stopped outcome, per stop width s in {0.5%,1%,2%}
  (stop fills modeled AT the stop price - gap-through risk ignored and
   documented; a stop wider than the eventual MAE never triggers)

Usage: python run_support_resistance.py [--smoke]
Writes findings/support-resistance/{study_results.json,study.md}
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
from intraday.forward import attach_forward_returns, build_next_day  # noqa: E402
from intraday.stats import round_block, summarize  # noqa: E402

SLAB = os.path.join(loader.REPO_ROOT, "research", "strategy-lab")
PANEL_PATH = os.path.join(SLAB, ".cache", "intraday_panel.parquet")
GRID_PATH = os.path.join(SLAB, ".cache", "intraday_grid5m.parquet")
OUT_DIR = os.path.join(SLAB, "findings", "support-resistance")

STOPS = (0.005, 0.01, 0.02)


def add_levels(panel):
    p = panel.sort_values(["ticker", "date"]).copy()
    g = p.groupby("ticker")
    for n_, tag in ((5, "l5"), (20, "l20")):
        p[f"hi_{tag}"] = g["day_high"].transform(
            lambda s: s.shift(1).rolling(n_, min_periods=max(3, n_ // 2)).max())
        p[f"lo_{tag}"] = g["day_low"].transform(
            lambda s: s.shift(1).rolling(n_, min_periods=max(3, n_ // 2)).min())
    return p.sort_values(["date", "ticker"]).reset_index(drop=True)


def first_cross(C, cond):
    """First index where cond(row-wise bool matrix over C columns) holds."""
    any_hit = cond.any(axis=1)
    idx = np.argmax(cond, axis=1).astype(float)
    idx[~any_hit] = np.nan
    return idx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()

    panel = pd.read_parquet(PANEL_PATH)
    ok = ((panel["n_bars_day"] >= 50) & (panel["day_open"] > 0) &
          (panel["day_close"] > 0) & (panel["day_ret_oc"].abs() <= 0.315) &
          panel["market"].notna() & (panel["day_vol"] > 0))
    panel = panel[ok].reset_index(drop=True)
    if args.smoke:
        dates = sorted(panel["date"].unique())[-15:]
        panel = panel[panel["date"].isin(dates)].reset_index(drop=True)

    panel = add_levels(panel)
    marks = [int(m) for m in session.GRID_MARKS]
    cols = ["date", "ticker"]
    for m in marks:
        cols += [f"c{m:04d}"]
    g = pd.read_parquet(GRID_PATH, columns=cols)
    g = (g.merge(panel[["date", "ticker"]], on=["date", "ticker"], how="inner")
          .sort_values(["date", "ticker"]).reset_index(drop=True))
    assert len(g) == len(panel)
    C = g[[f"c{m:04d}" for m in marks]].to_numpy(dtype=float)
    nd = build_next_day(panel)
    gcloses = g[["date", "ticker"] + [f"c{m:04d}" for m in marks]]

    res = {}
    for tag, side in (("l20", "sup"), ("l20", "res"),
                      ("l5", "sup"), ("l5", "res")):
        lvl = panel[f"lo_{tag}" if side == "sup" else f"hi_{tag}"].to_numpy(float)
        with np.errstate(all="ignore"):
            cond = np.isfinite(lvl)[:, None] & (
                (C < lvl[:, None]) if side == "sup" else (C > lvl[:, None]))
        idx = first_cross(C, cond)
        has = np.isfinite(idx)
        rr = np.where(has)[0]
        ev = pd.DataFrame({
            "date": panel["date"].to_numpy()[rr],
            "ticker": panel["ticker"].to_numpy()[rr],
            "market": panel["market"].to_numpy()[rr],
            "event_mark": np.array(marks)[idx[rr].astype(int)],
            "event_price": C[rr, idx[rr].astype(int)],
        })
        if len(ev) < 100:
            continue
        ev = attach_forward_returns(ev, gcloses, "event_price", "event_mark")
        ev = ev.merge(g[["date", "ticker", "c1530"]], on=["date", "ticker"],
                      how="left")
        with np.errstate(all="ignore"):
            ev["f_dayclose"] = ev["c1530"] / ev["event_price"] - 1.0
        ev = ev.merge(nd, on=["ticker", "date"], how="left")
        with np.errstate(all="ignore"):
            ev["nxo"] = ev["next_open"] / ev["event_price"] - 1.0
            ev["nxc"] = ev["next_close"] / ev["event_price"] - 1.0

        # MAE to day end: worst grid close AFTER the break mark vs entry
        rows_pos = {k: i for i, k in enumerate(zip(panel["date"], panel["ticker"]))}
        mae = np.full(len(ev), np.nan)
        ekeys = list(zip(ev["date"], ev["ticker"]))
        erows = np.array([rows_pos[k] for k in ekeys], dtype=int)
        for i, (r, j0) in enumerate(zip(erows, idx[rr].astype(int))):
            seg = C[r, j0 + 1:]
            seg = seg[np.isfinite(seg)]
            if len(seg):
                mae[i] = (seg.min() / ev["event_price"].to_numpy()[i]) - 1.0
        ev["mae_to_close"] = mae

        outs = ("f005", "f030", "f060", "f120", "f_dayclose", "nxo", "nxc")
        blk = {"n": int(len(ev))}
        for oc in outs:
            blk[oc] = summarize(ev[oc])
        blk["mae"] = {
            "median": float(np.nanmedian(mae)),
            "p25": float(np.nanpercentile(mae, 25)),
            "p75": float(np.nanpercentile(mae, 75)),
            "beyond_-2%": float(np.nanmean(mae <= -0.02)),
            "beyond_-5%": float(np.nanmean(mae <= -0.05)),
        }

        # stop-loss simulation (fills at stop, no gap modeling)
        stops_blk = {}
        held = ev["f_dayclose"].to_numpy(dtype=float)
        for s in STOPS:
            trig = ~np.isfinite(mae) | (mae <= -s)
            stopped_ret = np.where(trig, -s * (1 - 0.001), held)  # cost approx
            diff = held - stopped_ret
            ok_held = np.isfinite(held) & np.isfinite(stopped_ret)
            stops_blk[f"stop={s:.1%}"] = {
                "triggerRate": float(np.mean(trig[ok_held])) if ok_held.any() else None,
                "avgHeld": float(np.nanmean(held)),
                "avgStopped": float(np.mean(stopped_ret[ok_held])) if ok_held.any() else None,
                "missedBounceShare": float(np.nanmean(diff[ok_held] > 0)),
                "p95HeldLossAvoided": (float(np.nanpercentile(
                    np.where(ok_held, held - (-s), np.nan), 95))
                    if ok_held.any() else None),
                "maeCappedAt": float(-s),
            }
        blk["stops"] = stops_blk
        keyname = f"{side.upper()}_{tag}"
        res[keyname] = blk
        print(f"{keyname}: n={len(ev):,}")

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "smoke" if args.smoke else "full",
        "definitions": {
            "levels": "prior-session rolling 5/20-day high/low (shift1)",
            "break": "first 5-min grid close beyond the level",
            "mae": "min post-break grid close / break price - 1 until day end",
            "stopModel": "fill at stop price, no gap-through; trigger when "
                         "MAE<=-s; comparison vs holding to day close",
        },
        "sample": {"rows": int(len(panel)), "days": int(panel["date"].nunique())},
        "results": res,
        "pitNote": "levels from prior sessions; outcomes after the mark",
        "runtimeSec": round(time.time() - t0, 1),
    }
    out = round_block(out)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "study_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    md = ["# 지지/저항 돌파 & 손절 연구 (step 13)\n"]
    for keyname, b in res.items():
        md.append(f"\n## {keyname} (n={b['n']:,})\n")
        md.append("| 결과 | mean | median | winRate | t |")
        md.append("|---|---:|---:|---:|---:|")
        for oc in ("f030", "f120", "f_dayclose", "nxo", "nxc"):
            st = b[oc]
            md.append(f"| {oc} | {(st.get('mean') or 0)*100:+.3f}% | "
                      f"{(st.get('median') or 0)*100:+.3f}% | "
                      f"{(st.get('winRate') or 0)*100:.1f}% | "
                      f"{st.get('t') if st.get('t') is not None else float('nan'):+.2f} |")
        md.append(f"- MAE 중앙값 {b['mae']['median']*100:+.2f}% / "
                  f"-2% 초과 {b['mae']['beyond_-2%']*100:.0f}% / "
                  f"-5% 초과 {b['mae']['beyond_-5%']*100:.0f}%")
        for s, sb in b["stops"].items():
            md.append(f"- {s}: 발동 {sb['triggerRate']*100:.0f}% · 보유시 평균 "
                      f"{sb['avgHeld']*100:+.3f}% vs 손절시 {sb['avgStopped']*100:+.3f}%"
                      f" · 반등놓침 {sb['missedBounceShare']*100:.0f}%")
    with open(os.path.join(OUT_DIR, "study.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    print(json.dumps({"mode": out["mode"], "runtimeSec": out["runtimeSec"]}))
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
