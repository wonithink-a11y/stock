#!/usr/bin/env python
"""Volume + price-action events (directive step 10).

A  LOW + VOLUME SPIKE    : day low prints with a volume spike -> recovery?
B  HIGH + VOLUME SPIKE   : symmetric at the day high.
C  BREAKOUT + VOLUME     : first grid close above prior-20-session high,
                           with/without volume spike -> continuation?
D  BREAKOUT FAILURE      : breakout that falls back below the level same day.

Volume is NEVER absolute: spike ratio = bucket volume / mean volume of the
buckets BEFORE it in the SAME session (past-only, PIT-safe), evaluated at
the extreme/breakout 5-minute bucket. Thresholds are grids.

Levels come from the PANEL itself, shift(1) rolling windows of PRIOR
sessions only - no future rows enter any feature.

Usage: python run_volume_price.py [--smoke]
Writes findings/volume-price-events/{study_results.json,study.md}
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
from intraday.stats import paired_date_diff_ttest, round_block, summarize  # noqa: E402

SLAB = os.path.join(loader.REPO_ROOT, "research", "strategy-lab")
PANEL_PATH = os.path.join(SLAB, ".cache", "intraday_panel.parquet")
GRID_PATH = os.path.join(SLAB, ".cache", "intraday_grid5m.parquet")
OUT_DIR = os.path.join(SLAB, "findings", "volume-price-events")

SPIKE_THR = (2.0, 3.0, 5.0)
OUTS_AB = ("f030", "f060", "f120", "f_dayclose", "nxo", "nxc")
OUTS_CD = ("f030", "f060", "f120", "f_dayclose", "nxo", "nxc")


def load_aligned(panel):
    marks = [int(m) for m in session.GRID_MARKS]
    cols = ["date", "ticker"]
    for m in marks:
        cols += [f"c{m:04d}", f"v{m:04d}"]
    grid = pd.read_parquet(GRID_PATH, columns=cols)
    panel = panel.sort_values(["date", "ticker"]).reset_index(drop=True)
    grid = (grid.merge(panel[["date", "ticker"]], on=["date", "ticker"],
                       how="inner")
                .sort_values(["date", "ticker"]).reset_index(drop=True))
    if len(grid) != len(panel):
        raise RuntimeError("grid/panel key mismatch")
    return grid, marks


def spike_matrix(vmat):
    """spike[j] = v[j] / mean(v[0..j-1]); NaN before >=6 prior buckets."""
    v = np.where(np.isfinite(vmat), vmat, 0.0)
    cnt = np.isfinite(vmat).astype(np.int64)
    csum = np.cumsum(v, axis=1)
    ccnt = np.cumsum(cnt, axis=1)
    prev_sum = csum - v
    prev_cnt = ccnt - cnt
    with np.errstate(all="ignore"):
        base = np.where(prev_cnt >= 6, prev_sum / np.maximum(prev_cnt, 1), np.nan)
        out = np.where((vmat > 0) & np.isfinite(base), vmat / base, np.nan)
    out[prev_cnt < 6] = np.nan
    return out


def first_true_index(bool_mat):
    """First True per row -> (idx float, any bool)."""
    any_hit = bool_mat.any(axis=1)
    idx = np.argmax(bool_mat, axis=1).astype(float)
    idx[~any_hit] = np.nan
    return idx, any_hit


def add_levels(panel):
    """Rolling PRIOR-session high/low levels (shift(1) => PIT-safe)."""
    p = panel.sort_values(["ticker", "date"]).copy()
    g = p.groupby("ticker")
    for n_, tag in ((5, "l5"), (20, "l20")):
        p[f"hi_{tag}"] = g["day_high"].transform(
            lambda s: s.shift(1).rolling(n_, min_periods=max(3, n_ // 2)).max())
        p[f"lo_{tag}"] = g["day_low"].transform(
            lambda s: s.shift(1).rolling(n_, min_periods=max(3, n_ // 2)).min())
    return p.sort_values(["date", "ticker"]).reset_index(drop=True)


def bucket_of(hhmm_arr, n_marks):
    mins = (np.nan_to_num(hhmm_arr) // 100) * 60 + np.nan_to_num(hhmm_arr) % 100
    j = ((mins - 541) // 5).astype(float)
    j[np.nan_to_num(hhmm_arr) <= 540] = 0
    j[~np.isfinite(hhmm_arr)] = np.nan
    return np.clip(j, 0, n_marks - 1)


def stats_vs_quiet(ev, m, mo, outs):
    """Per-outcome: event summary + excess vs quiet-control benchmark +
    paired diff test."""
    eb = {"n": int(m.sum()), "nQuiet": int(mo.sum())}
    for oc in outs:
        st = summarize(ev.loc[m.to_numpy(), oc])
        other = ev.loc[mo.to_numpy()]
        bm = other.dropna(subset=[oc]).groupby(["date", "market"])[oc].mean()
        e_sub = ev.loc[m.to_numpy()].dropna(subset=[oc])
        key = pd.MultiIndex.from_arrays([e_sub["date"], e_sub["market"]])
        exc = (e_sub[oc].to_numpy() -
               bm.reindex(key).to_numpy(dtype=float))
        exc = exc[np.isfinite(exc)]
        if len(exc):
            st["meanExc"] = float(np.mean(exc))
            st["winRateExc"] = float((exc > 0).mean())
            st["nExc"] = int(len(exc))
            if len(exc) > 1 and np.std(exc, ddof=1) > 0:
                tt, pv = sps.ttest_1samp(exc, 0.0)
                st["tExc"], st["pExc"] = float(tt), float(pv)
        eb[oc] = st
        eb[f"diff_{oc}"] = paired_date_diff_ttest(ev, m, mo, oc)
    return eb


def build_events(panel, ext_t, ext_px):
    ev = pd.DataFrame({
        "date": panel["date"].to_numpy(),
        "ticker": panel["ticker"].to_numpy(),
        "market": panel["market"].to_numpy(),
        "event_mark": pd.Series(ext_t).fillna(1530).to_numpy(),
        "event_price": ext_px})
    return ev


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
    grid, marks = load_aligned(panel)
    n = len(panel)
    C = grid[[f"c{m:04d}" for m in marks]].to_numpy(dtype=float)
    V = grid[[f"v{m:04d}" for m in marks]].to_numpy(dtype=float)
    SPK = spike_matrix(V)
    print(f"aligned rows={n:,}; matrices ready ({time.time()-t0:.0f}s)")

    nd = build_next_day(panel)
    gcloses = grid[["date", "ticker"] + [f"c{m:04d}" for m in marks]]

    def with_next(ev):
        ev = attach_forward_returns(ev, gcloses, "event_price", "event_mark")
        ev = ev.merge(grid[["date", "ticker", "c1530"]],
                      on=["date", "ticker"], how="left")
        with np.errstate(all="ignore"):
            ev["f_dayclose"] = ev["c1530"] / ev["event_price"] - 1.0
        ev = ev.merge(nd, on=["ticker", "date"], how="left")
        with np.errstate(all="ignore"):
            ev["nxo"] = ev["next_open"] / ev["event_price"] - 1.0
            ev["nxc"] = ev["next_close"] / ev["event_price"] - 1.0
        return ev

    res = {}
    rows = np.arange(n)

    # ---------------- A/B : day extremes with/without volume spike --------
    lo_t = panel["day_low_time"].to_numpy(dtype=float)
    hi_t = panel["day_high_time"].to_numpy(dtype=float)
    for ext_t, ext_px, label, quiet in (
            (lo_t, panel["day_low"].to_numpy(dtype=float), "A_lowSpike", 1.2),
            (hi_t, panel["day_high"].to_numpy(dtype=float), "B_highSpike", 1.2)):
        bj = bucket_of(ext_t, len(marks))
        valid = np.isfinite(bj) & np.isfinite(ext_px) & (ext_px > 0)
        spike_at = np.full(n, np.nan)
        ok_rows = rows[valid]
        spike_at[ok_rows] = SPK[ok_rows, bj[ok_rows].astype(int)]
        blk = {}
        for thr in SPIKE_THR:
            m = pd.Series(spike_at >= thr).fillna(False)
            mo = pd.Series(valid) & pd.Series(spike_at < quiet).fillna(False)
            ev = with_next(build_events(panel, ext_t, ext_px))
            blk[f"spike>={thr}"] = stats_vs_quiet(
                ev, m, mo,
                ("f030", "f060", "f120", "f_dayclose", "nxo", "nxc"))
        res[label] = blk
        print(f"{label}: spike>=3.0 events={int((spike_at >= 3.0).sum()):,}")

    # ---------------- C/D : 20d-high breakout + volume --------------------
    lvl = panel["hi_l20"].to_numpy(dtype=float)
    above = np.isfinite(lvl)[:, None] & (C > lvl[:, None])
    prev_above = np.zeros_like(above)
    prev_above[:, 1:] = above[:, :-1]
    cross = above & ~prev_above
    cidx, any_cross = first_true_index(cross)
    has_bo = any_cross.copy()

    # breakout-time spike ratio at the crossing bucket
    bo_spike = np.full(n, np.nan)
    vr = rows[np.isfinite(cidx)]
    bo_spike[vr] = SPK[vr, cidx[vr].astype(int)]

    # D: failure = close back below level at some LATER grid point same day
    below_again = np.isfinite(lvl)[:, None] & (C < lvl[:, None])
    fail_after = np.zeros_like(below_again)
    for j in range(1, below_again.shape[1]):
        fail_after[:, j] = below_again[:, j] & above[:, :j].any(axis=1)
    fidx, any_fail_rel = first_true_index(fail_after)
    # restrict to rows that had a breakout earlier than the fallback
    any_fail = np.isfinite(fidx) & np.isfinite(cidx) & (fidx > cidx)

    # outcomes from the breakout mark price (grid close at cross bucket)
    bo_mark = np.full(n, np.nan)
    bo_px = np.full(n, np.nan)
    bo_mark[np.isfinite(cidx)] = np.array(marks)[cidx[np.isfinite(cidx)].astype(int)]
    rr = np.isfinite(cidx)
    bo_px[rr] = C[rr, cidx[rr].astype(int)]
    ev_bo = pd.DataFrame({
        "date": panel["date"].to_numpy(), "ticker": panel["ticker"].to_numpy(),
        "market": panel["market"].to_numpy(),
        "event_mark": pd.Series(bo_mark), "event_price": pd.Series(bo_px)})
    ev_bo = ev_bo.dropna(subset=["event_mark", "event_price"]).copy()
    ev_bo = with_next(ev_bo)

    # map row-level flags onto the event frame order
    pkeys = list(zip(panel["date"], panel["ticker"]))
    pos = {k: i for i, k in enumerate(pkeys)}
    key_ser = list(zip(ev_bo["date"], ev_bo["ticker"]))
    epos = np.array([pos[k] for k in key_ser], dtype=int)

    m_volhi = {}
    for thr in SPIKE_THR:
        m_volhi[thr] = pd.Series(bo_spike[epos] >= thr, index=ev_bo.index)

    failed_ser = pd.Series(any_fail[epos], index=ev_bo.index)
    blk_cd = {"nBreakouts": int(len(ev_bo))}
    for thr in SPIKE_THR:
        mv = m_volhi[thr].fillna(False)
        ml = (~m_volhi[thr]).fillna(False) & ~failed_ser
        cont = stats_vs_quiet(ev_bo[~failed_ser], mv[~failed_ser],
                              ml[~failed_ser], OUTS_CD)
        blk_cd[f"cont_spike>={thr}"] = cont
        mf = (failed_ser & mv.fillna(False))
        mfl = (failed_ser & ~mv.fillna(False))
        if mf.sum() >= 50:
            blk_cd[f"fail_spike>={thr}"] = {
                "n": int(mf.sum()),
                **{oc: summarize(ev_bo.loc[mf.to_numpy(), oc]) for oc in OUTS_CD},
                "vsQuietFail": {oc: paired_date_diff_ttest(ev_bo[failed_ser], mf, mfl, oc)
                                for oc in OUTS_CD}}
    res["C_breakout20d"] = blk_cd

    out = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "smoke" if args.smoke else "full",
        "definitions": {
            "spikeRatio": "bucket volume / mean volume of PRIOR buckets in "
                          "the same session (min 6 prior buckets)",
            "levels": "prior-session rolling 5/20-day high/low from the "
                      "panel, shift(1)",
            "breakout": "first 5-min grid close above hi_l20; failure = a "
                        "later grid close back below it, same session",
            "outcomes": "from the extreme/breakout mark price; nxo/nxc = "
                        "next session open/close",
            "quietControl": "same-side extremes with spike<1.2",
        },
        "sample": {"rows": int(n), "days": int(panel["date"].nunique())},
        "results": res,
        "pitNote": "all conditions use data at/before their decision mark",
        "runtimeSec": round(time.time() - t0, 1),
    }
    out = round_block(out)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "study_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)

    md = ["# Volume x Price Action 이벤트 (step 10)\n"]
    for lab in ("A_lowSpike", "B_highSpike"):
        b3 = res[lab]["spike>=3.0"]
        md.append(f"\n## {lab} (spike>=3.0 vs quiet<1.2)\n")
        md.append("| 결과 | n | mean | meanExc | t | 승률(exc) | diff-t(vs quiet) |")
        md.append("|---|---:|---:|---:|---:|---:|---:|")
        for oc in OUTS_AB:
            st = b3.get(oc, {})
            dv = b3.get(f"diff_{oc}", {})
            md.append(f"| {oc} | {st.get('n')} | {(st.get('mean') or 0)*100:+.3f}% | "
                      f"{(st.get('meanExc') if st.get('meanExc') is not None else float('nan'))*100:+.3f}% | "
                      f"{st.get('tExc') if st.get('tExc') is not None else float('nan'):+.2f} | "
                      f"{(st.get('winRateExc') if st.get('winRateExc') is not None else float('nan'))*100:.1f}% | "
                      f"{dv.get('t') if dv.get('t') is not None else float('nan'):+.2f} |")
    cb = res["C_breakout20d"]
    md.append(f"\n## C/D 돌파(20d high): 전체 {cb['nBreakouts']:,}건\n")
    for thr in SPIKE_THR:
        k = f"cont_spike>={thr}"
        if k in cb:
            st = cb[k]["f_dayclose"]
            dnx = cb[k].get("diff_nxc@x") or {}
            md.append(f"- spike>={thr}: 당일종가 exc {(st.get('meanExc') or float('nan'))*100:+.3f}%"
                      f" (t={st.get('tExc') if st.get('tExc') is not None else float('nan'):+.2f}),"
                      f" 익일 diff-t={dnx.get('t') if dnx.get('t') is not None else float('nan'):+.2f}")
    fk = [k for k in cb if k.startswith("fail_")]
    for k in fk[:1]:
        md.append(f"- 실패(돌파 후 재이탈) 이벤트 n={cb[k]['n']:,}"
                  f" — 상세 JSON 참고")
    with open(os.path.join(OUT_DIR, "study.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))

    print(json.dumps({"mode": out["mode"], "rows": out["sample"]["rows"],
                      "runtimeSec": out["runtimeSec"]}))
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
