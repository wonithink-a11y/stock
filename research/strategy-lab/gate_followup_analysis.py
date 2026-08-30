#!/usr/bin/env python
"""게이트 검증 후속 분석: rv20 상위 decile과 LOWMOM60/REV20 시그널 겹침 분석"""

import json
import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from liquidity_factor_study import (
    DATA, REPO_ROOT,
    load_full_ohlc, features_from_ohlc,
    monthly_rebalance_dates, LIQ_THRESHOLD,
)

OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-08-26-universe-gate")

MIN_NAMES_PER_DATE = 30
DECILE_HORIZONS = ["fwd_d20", "fwd_d60", "fwd_d120"]

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    
    # 1. Load panel and features (reuse existing computed data)
    print("Loading A4 panel...")
    panel = pd.read_parquet(DATA, columns=["ticker", "date", "fwd_d20", "fwd_d60", "fwd_d120"])
    wanted = set(panel["ticker"].unique())

    print("Streaming full A2a OHLCV + computing features...")
    full, stream_stats = load_full_ohlc(set(pd.read_parquet(DATA, columns=['ticker'])['ticker'].unique()))
    frames = []
    for t, rows in full.items():
        f = features_from_ohlc(rows)
        f.insert(0, "ticker", t)
        frames.append(f)
    feats = pd.concat(frames, ignore_index=True)

    df = panel.merge(feats, on=["ticker", "date"], how="inner")
    for h in (20, 60, 120):
        a, b = df[f"fwd_d{h}_x"], df[f"fwd_d{h}_y"]
        m = a.notna() & b.notna()
        df[f"fwd_d{h}"] = df[f"fwd_d{h}_x"]
    df = df.drop(columns=[c for c in df.columns if c.endswith("_x") or c.endswith("_y")])

    df["dv20"] = np.exp(df["dv20_log"])
    rebal = set(monthly_rebalance_dates(df["date"]))
    rb = df[df["date"].isin(rebal)].copy()

    # rv20 decile on FULL cross-section each date
    def _q(grp):
        if len(grp) < 30:
            grp["rv_decile"] = np.nan
            return grp
        grp["rv_decile"] = pd.qcut(grp["rv20_pct"].rank(method="first"), 10, labels=False) + 1
        return grp

    rb_all = df.dropna(subset=["rv20_pct"]).groupby("date", group_keys=False).apply(
        lambda g: g.assign(rv_decile=pd.qcut(g["rv20_pct"].rank(method="first"), 10, labels=False)+1) if len(g)>=30 else g.assign(rv_decile=np.nan)
    )
    
    # Mark top decile flags
    rv_top = rb_all[rb_all["rv_decile"] == 10][["ticker", "date"]].copy()
    rv_top["is_rv_top"] = True
    
    # Compute mom60, mom20 deciles on full cross-section
    def add_mom_decile(df_sub, feat, col_name):
        def _qd(grp):
            if len(grp) < 30:
                grp[col_name] = np.nan
                return grp
            grp[col_name] = pd.qcut(grp[feat].rank(method="first"), 10, labels=False) + 1
            return grp
        return df.dropna(subset=[feat]).groupby("date", group_keys=False).apply(_qd)

    # We need mom60 and mom20 deciles on full cross-section
    mom60_dec = df.dropna(subset=["mom60"]).groupby("date", group_keys=False).apply(
        lambda g: g.assign(mom60_decile=pd.qcut(g["mom60"].rank(method="first"), 10, labels=False)+1) if len(g)>=30 else g.assign(mom60_decile=np.nan)
    )
    mom20_dec = df.dropna(subset=["mom20"]).groupby("date", group_keys=False).apply(
        lambda g: g.assign(mom20_decile=pd.qcut(g["mom20"].rank(method="first"), 10, labels=False)+1) if len(g)>=30 else g.assign(mom20_decile=np.nan)
    )

    # Merge back to rb
    rb = df[df["date"].isin(set(pd.read_parquet(DATA, columns=['date'])['date'].unique()))].copy()  # All dates
    # Actually just use the rebalance dates rb
    rb = df[df["date"].isin(pd.Series(list(set(pd.read_parquet(DATA, columns=['date'])['date'].unique()))))].copy()
    rebal = set(pd.read_parquet(DATA, columns=['date'])['date'].unique())
    # Actually simpler: 
    rebal = set(monthly_rebalance_dates(df["date"]))
    rb = df[df["date"].isin(rebal)].copy()

    # Merge rv_top flag
    rv_top_flags = set(map(tuple, rv_top[["ticker", "date"]].to_numpy()))
    key = list(zip(rb["ticker"], rb["date"]))
    rb["is_rv_top"] = [tuple(k) not in rv_top_flags for k in zip(rb["ticker"], rb["date"])]
    # Actually rv_top is top decile, so we want to KNOW if it's in top
    rv_top_flags_true = set(map(tuple, rv_top[["ticker", "date"]].to_numpy()))
    rb["is_rv_top10"] = [tuple(k) in rv_top_flags_true for k in zip(rb["ticker"], rb["date"])]

    # Merge mom60/mom20 deciles
    mom60_map = mom60_dec.set_index(["ticker", "date"])["mom60_decile"].to_dict()
    mom20_map = mom20_dec.set_index(["ticker", "date"])["mom20_decile"].to_dict()
    rb["mom60_decile"] = [mom60_map.get(tuple(k), np.nan) for k in zip(rb["ticker"], rb["date"])]
    rb["mom20_decile"] = [mom20_map.get(tuple(k), np.nan) for k in zip(rb["ticker"], rb["date"])]

    # Now analyze
    print("\n=== rv20 Top Decile Composition Analysis ===")
    rv_top_df = rb[rb["is_rv_top10"] == True]
    print(f"rv20 top decile rows: {len(rv_top_df)}")
    
    # Among rv20 top decile, what % are LOWMOM60 (mom60 decile 1)?
    mom60_low = rb[rb["mom60_decile"] == 1]
    mom60_low_in_rv_top = rb[(rb["is_rv_top10"]) & (rb["mom60_decile"] == 1)]
    print(f"LOWMOM60 (mom60 D1) total: {len(rb[rb['mom60_decile']==1])}")
    print(f"LOWMOM60 in rv20 top10: {len(mom60_low_in_rv_top)}")
    print(f"  Overlap rate: {len(mom60_low_in_rv_top)/len(rb[rb['mom60_decile']==1])*100:.1f}%")
    print(f"  Of rv_top10, % that are LOWMOM60: {len(mom60_low_in_rv_top)/len(rv_top_df)*100:.1f}%")

    mom20_low = rb[rb["mom20_decile"] == 1]
    mom20_low_in_rv_top = rb[(rb["is_rv_top10"]) & (rb["mom20_decile"] == 1)]
    print(f"\nREV20 (mom20 D1) total: {len(rb[rb['mom20_decile']==1])}")
    print(f"REV20 in rv20 top10: {len(mom20_low_in_rv_top)}")
    print(f"  Overlap rate: {len(mom20_low_in_rv_top)/len(rb[rb['mom20_decile']==1])*100:.1f}%")
    print(f"  Of rv_top10, % that are REV20: {len(mom20_low_in_rv_top)/len(rv_top_df)*100:.1f}%")

    # Combined
    both_low = rb[(rb["mom60_decile"]==1) & (rb["mom20_decile"]==1)]
    both_in_rv_top = rb[(rb["is_rv_top10"]) & (rb["mom60_decile"]==1) & (rb["mom20_decile"]==1)]
    print(f"\nBoth LOWMOM60 & REV20: {len(both_low)}")
    print(f"Both in rv_top10: {len(both_in_rv_top)} ({len(both_in_rv_top)/len(both_low)*100:.1f}%)")

    # What % of rv_top10 are LOWMOM60 or REV20?
    rv_top_either = rb[(rb["is_rv_top10"]) & ((rb["mom60_decile"]==1) | (rb["mom20_decile"]==1))]
    print(f"\nrv_top10 that are LOWMOM60 or REV20: {len(rv_top_either)} / {len(rv_top_df)} = {len(rv_top_either)/len(rv_top_df)*100:.1f}%")

    # Check forward returns of rv_top10
    print("\n=== Forward Returns of rv20 Top Decile ===")
    for h in ["fwd_d20", "fwd_d60", "fwd_d120"]:
        rv_top_h = rv_top_df[h].dropna()
        all_h = rb[h].dropna()
        print(f"  {h}: rv_top10 mean={rv_top_h.mean():+.4f}, all mean={all_h.mean():+.4f}, diff={rv_top_h.mean()-all_h.mean():+.4f}")

    # Check what happens if we exclude rv_top10: what % of LOWMOM60/REV20 signals are removed?
    print("\n=== Signal Removal by Excluding rv_top10 ===")
    mom60_removed = len(mom60_low_in_rv_top) / len(mom60_low) * 100
    mom20_removed = len(mom20_low_in_rv_top) / len(mom20_low) * 100
    print(f"LOWMOM60 signals removed by rv_top exclusion: {mom60_removed:.1f}%")
    print(f"REV20 signals removed by rv_top exclusion: {mom20_removed:.1f}%")

    # Check forward returns of signals AFTER removing rv_top10
    print("\n=== Forward Returns of Signals (with/without rv_top10) ===")
    for label, feat in [("LOWMOM60", "mom60"), ("REV20", "mom20")]:
        sig_all = rb[rb[f"{feat}_decile"] == 1] if feat == "mom60" else rb[rb["mom20_decile"] == 1]
        sig_kept = sig_all[sig_all["is_rv_top10"] == False]  # Not in rv_top10
        sig_removed = sig_all[sig_all["is_rv_top10"] == True]
        for h in DECILE_HORIZONS:
            all_h = sig_all[h].dropna()
            kept_h = sig_kept[h].dropna()
            rem_h = sig_removed[h].dropna()
            print(f"  {label} {h}: all={all_h.mean():+.4f}, kept={kept_h.mean():+.4f} (n={len(kept_h)}), removed={rem_h.mean():+.4f} (n={len(rem_h)})")

if __name__ == "__main__":
    main()