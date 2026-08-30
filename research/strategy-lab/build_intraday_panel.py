#!/usr/bin/env python
"""Stage-A master pass over the minute_raw mirror -> research feature caches.

Produces (under research/strategy-lab/.cache/, gitignored):
  intraday_panel.parquet   one row per ticker-day, scalar features (OPEN30,
                           day aggregates, slot volumes/amounts)
  intraday_grid5m.parquet  per ticker-day x 78 five-minute marks:
                           c#### as-of close, v#### bucket volume,
                           h#### bucket max high, l#### bucket min low

Definitions fixed here; every downstream study inherits them.
  - Session filter: bars stamped hhmm in [0900, 1530]. The '15:32' artifact
    rows are dropped and counted per day.
  - AS-OF price at mark M = close of the LAST bar with hhmm <= M. Missing
    bars (no trades) never produce fabricated prices; illiquid names get a
    stale-but-real price, NaN when nothing traded at or before the mark.
  - OPEN30 formation window = bars stamped 0900..0929 (30 slots);
    price_at_30m = as-of close at mark 0930;
    open_price = open of the FIRST bar with hhmm <= 0930.
  - Grid bucket j covers (mark_{j-1}, mark_j] (bucket 0 also holds the
    09:00 bar). Bucket v/h/l are within-bucket aggregates. Grid close is
    as-of (cumulative), so forward returns are always measurable.
  - Relative-volume baselines: trailing EXPANDING mean of the same metric
    for that ticker SHIFTED one session (past sessions only, PIT-safe;
    min_periods=5 else NaN).
  - Liquidity baseline: trailing expanding mean of day_amt shifted one
    session; liq_decile is the per-date cross-sectional decile of it.

Usage:
  python build_intraday_panel.py             # full pass (all partitions)
  python build_intraday_panel.py --smoke     # last 8 dates, 60 tickers
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

CACHE_DIR = os.path.join(loader.REPO_ROOT, "research", "strategy-lab", ".cache")
PANEL_PATH = os.path.join(CACHE_DIR, "intraday_panel.parquet")
GRID_PATH = os.path.join(CACHE_DIR, "intraday_grid5m.parquet")

UNIVERSE_PATH = os.path.join(loader.REPO_ROOT, "data", "backfill", "universe",
                             "a1a", "current.jsonl")

PATH_MARKS = (905, 910, 915, 920, 925)         # r5..r25 (r30 comes from p30)
REL_VOL_COLS = ("w_amt", "day_vol",
                "v_w0930_1030", "v_w1030_1130", "v_w1130_1300",
                "v_w1300_1400", "v_w1400_1500", "v_w1500_1530")


def load_universe_map():
    """ticker -> (market, sector) from A1a current.jsonl (read-only)."""
    out = {}
    with open(UNIVERSE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            out[r["ticker"]] = (r.get("market"), r.get("sector"))
    return out


def asof_close_matrix(df, marks):
    """All as-of closes in ONE numpy pass.

    Returns ndarray shape (len(marks), n_tickers); entry NaN when the ticker
    has no bar at or before that mark. df must be sorted by (ticker, hhmm).
    """
    codes, starts = np.unique(df["ticker"].to_numpy(), return_index=True)
    ends = np.append(starts[1:], len(df))
    hh = df["hhmm"].to_numpy()
    cl = df["close"].to_numpy()
    out = np.full((len(marks), len(codes)), np.nan)
    for i, (s, e) in enumerate(zip(starts, ends)):
        seg = hh[s:e]
        idx = np.searchsorted(seg, marks, side="right") - 1
        ok = idx >= 0
        out[ok, i] = cl[s + idx[ok]]
    return codes, out


def process_day(date_str):
    df = loader.read_day(date_str)
    diag = {"date": date_str, "rows": 0, "offSessionRows": 0}
    if df is None or df.empty:
        return None, None, diag
    off = (df["hhmm"] < 900) | (df["hhmm"] > 1530)
    diag["offSessionRows"] = int(off.sum())
    df = df[~off]
    if df.empty:
        return None, None, diag
    diag["rows"] = int(len(df))
    df = df.sort_values(["ticker", "hhmm"], kind="stable").reset_index(drop=True)
    amt = (df["close"] * df["volume"]).astype(np.float64)

    # ---------- day level ----------
    df["_amt"] = amt
    g = df.groupby("ticker", sort=False)
    panel = g.agg(
        first_bar=("hhmm", "first"),
        last_bar=("hhmm", "last"),
        day_open=("open", "first"),
        day_close=("close", "last"),
        day_high=("high", "max"),
        day_low=("low", "min"),
        n_bars_day=("hhmm", "size"),
        day_vol=("volume", "sum"),
        day_amt=("_amt", "sum"),
    )
    panel["day_high_time"] = pd.Series(
        df["hhmm"].to_numpy()[g["high"].idxmax().to_numpy()], index=panel.index)
    panel["day_low_time"] = pd.Series(
        df["hhmm"].to_numpy()[g["low"].idxmin().to_numpy()], index=panel.index)

    # ---------- OPEN30 window ----------
    fo = df[(df["hhmm"] >= session.OPEN30_LO) & (df["hhmm"] <= session.OPEN30_HI)].copy()
    fo.reset_index(drop=True, inplace=True)
    fo["_fa"] = (fo["close"] * fo["volume"]).astype(np.float64)
    gf = fo.groupby("ticker", sort=False)
    w = gf.agg(w_high=("high", "max"), w_low=("low", "min"),
               n_bars_30=("high", "size"), w_vol=("volume", "sum"),
               w_amt=("_fa", "sum"), last_bar_30=("hhmm", "max"))
    pos_h = gf["high"].idxmax()
    pos_l = gf["low"].idxmin()
    w["w_high_time"] = pd.Series(
        fo["hhmm"].to_numpy()[pos_h.to_numpy()], index=pos_h.index)
    w["w_low_time"] = pd.Series(
        fo["hhmm"].to_numpy()[pos_l.to_numpy()], index=pos_l.index)

    a30 = df[df["hhmm"] <= session.OPEN30_MARK]
    ga = a30.groupby("ticker", sort=False)
    base = ga.agg(open_price=("open", "first"))

    left = panel.join(w, how="outer").join(base, how="outer")

    # ---------- slot-window volume / amount buckets ----------
    bidx = session.grid_bucket_index(df["hhmm"].to_numpy())
    tmp = pd.DataFrame({"ticker": df["ticker"].to_numpy(), "j": bidx,
                        "v": df["volume"].to_numpy(), "h": df["high"].to_numpy(),
                        "l": df["low"].to_numpy(), "a": amt.to_numpy()})
    bg = tmp.groupby(["ticker", "j"], sort=True).agg(
        v=("v", "sum"), h=("h", "max"), l=("l", "min"), a=("a", "sum"))
    cols = list(range(len(session.GRID_MARKS)))
    bvol = bg["v"].unstack(fill_value=np.nan).reindex(columns=cols)
    bhi = bg["h"].unstack(fill_value=np.nan).reindex(columns=cols)
    blo = bg["l"].unstack(fill_value=np.nan).reindex(columns=cols)
    bam = bg["a"].unstack(fill_value=np.nan).reindex(columns=cols)

    marks = session.GRID_MARKS
    codes, aclose = asof_close_matrix(df, marks.astype(np.int64))
    ac_df = pd.DataFrame(aclose.T, index=codes)          # tickers x 78
    data = {}
    for k, m in enumerate(marks):
        col = f"{m:04d}"
        data[f"c{col}"] = ac_df[k]
        data[f"v{col}"] = bvol[k]
        data[f"h{col}"] = bhi[k]
        data[f"l{col}"] = blo[k]
        data[f"a{col}"] = bam[k]
    grid = pd.DataFrame(data, index=bvol.index).astype(np.float32)

    # OPEN30 path prices come from the same as-of matrix (marks 905..925).
    mark_pos = {int(m): k for k, m in enumerate(marks)}
    for m in PATH_MARKS:
        left[f"p{m}"] = ac_df[mark_pos[m]]
    left["p_at30m"] = ac_df[mark_pos[session.OPEN30_MARK]]
    sub900 = df[df["hhmm"] <= 900]
    left["p900c"] = sub900.groupby(sub900["ticker"], sort=False)["close"].last()

    # slot window aggregates on the panel (volumes/amounts only here;
    # slot returns derive from grid closes inside studies)
    def _slot_sum(frame, start, end):
        ks = [k for k, mm in enumerate(marks) if start < mm <= end]
        return frame[ks].sum(axis=1, min_count=1)

    for label, s, e in session.TIME_WINDOWS[1:]:
        left[f"v_{label}"] = _slot_sum(bvol, s, e)
        left[f"amt_{label}"] = _slot_sum(bam, s, e)
    left["v_w0900_0930"] = left["w_vol"]

    return left, grid, diag


def add_trailing_baselines(panel):
    """PIT-safe trailing baselines + relative-volume columns.

    Requires panel sorted by (ticker, date) - expanding windows run in date
    order per ticker and use shift(1) so event-day data never enters its own
    baseline.
    """
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    for col in REL_VOL_COLS:
        base = panel.groupby("ticker")[col].transform(
            lambda s: s.shift(1).expanding(min_periods=5).mean())
        panel[f"rel_{col}"] = np.where((base > 0) & np.isfinite(base),
                                       panel[col] / base, np.nan)
    liq_base = panel.groupby("ticker")["day_amt"].transform(
        lambda s: s.shift(1).expanding(min_periods=20).mean())
    panel["liq_base"] = liq_base
    panel["liq_decile"] = (panel.groupby("date")["liq_base"]
                           .transform(lambda s: s.rank(pct=True))
                           .mul(10).pipe(np.ceil).clip(upper=10))
    return panel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    os.makedirs(CACHE_DIR, exist_ok=True)
    dates = loader.list_dates()
    print(f"partitions={len(dates)} ({dates[0]}..{dates[-1]})")

    smoke_dates = dates[-8:] if args.smoke else dates
    ticker_filter = None
    if args.smoke:
        probe = loader.read_day(smoke_dates[0], columns=("ticker", "close", "volume"))
        probe["_a"] = probe["close"] * probe["volume"]
        top = probe.groupby("ticker")["_a"].sum().sort_values(ascending=False)
        ticker_filter = set(top.index[:60])
        print(f"SMOKE ticker filter: {len(ticker_filter)} tickers")

    uni = load_universe_map()
    panels, grids = [], []
    diags = []
    for i, d in enumerate(smoke_dates, 1):
        p, g, diag = process_day(d)
        diags.append(diag)
        if p is None:
            print(f"  {i}/{len(smoke_dates)} {d}: EMPTY")
            continue
        p = p.reset_index().rename(columns={"index": "ticker"})
        p.insert(0, "date", d)
        if ticker_filter is not None:
            keep = p["ticker"].isin(ticker_filter)
            p = p[keep]
            g = g[g.index.isin(ticker_filter)]
        markets = p["ticker"].map(lambda t: uni.get(t, (None, None))[0])
        sectors = p["ticker"].map(lambda t: uni.get(t, (None, None))[1])
        p["market"] = markets
        p["sector"] = sectors
        panels.append(p)
        g2 = g.reset_index().rename(columns={"index": "ticker"})
        g2.insert(0, "date", d)
        grids.append(g2)
        if i % 20 == 0 or i == len(smoke_dates):
            print(f"  {i}/{len(smoke_dates)} days ({time.time()-t0:.0f}s)")

    panel = pd.concat(panels, ignore_index=True)
    grid = pd.concat(grids, ignore_index=True)

    float_cols = [c for c in panel.columns if c not in
                  ("date", "ticker", "market", "sector")]
    panel[float_cols] = panel[float_cols].astype(np.float32)

    # derived OPEN30 scalars (after dtype cast; float64 math then cast back)
    op = panel["open_price"].astype(float)
    p30 = panel["p_at30m"].astype(float)
    wh = panel["w_high"].astype(float)
    wl = panel["w_low"].astype(float)
    with np.errstate(all="ignore"):
        panel["r30"] = (p30 / op - 1).astype(np.float32)
        for m in PATH_MARKS:
            pm = panel[f"p{m}"].astype(float)
            panel[f"r{(m-900)//5*5:d}"] = (pm / op - 1).astype(np.float32)
        rng = wh - wl
        panel["range_position"] = np.where(rng > 0, (p30 - wl) / rng,
                                           np.nan).astype(np.float32)
        panel["w30_range"] = np.where(op > 0, rng / op, np.nan).astype(np.float32)
        panel["day_ret_oc"] = (panel["day_close"].astype(float) / op - 1).astype(np.float32)
        hi_first = panel["w_high_time"] <= panel["w_low_time"]
        both = panel["w_high_time"].notna() & panel["w_low_time"].notna() & \
            (panel["w_high_time"] != panel["w_low_time"])
        panel["hi_before_lo"] = np.where(both, hi_first, np.nan).astype(np.float32)

    panel = add_trailing_baselines(panel)

    panel.to_parquet(PANEL_PATH, index=False)
    grid.to_parquet(GRID_PATH, index=False)

    summary = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "smoke" if args.smoke else "full",
        "dates": [diags[0]["date"], diags[-1]["date"]],
        "days": int(len(diags)),
        "panelRows": int(len(panel)),
        "gridRows": int(len(grid)),
        "offSessionRowsDropped": int(sum(x.get("offSessionRows", 0) for x in diags)),
        "runtimeSec": round(time.time() - t0, 1),
        "panelPath": PANEL_PATH,
        "gridPath": GRID_PATH,
        "pitNote": "baselines are expanding means shifted one session "
                   "(event-day values never enter their own baseline)",
    }
    sp = os.path.join(CACHE_DIR, "intraday_panel_build_summary.json")
    with open(sp, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
