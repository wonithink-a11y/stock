#!/usr/bin/env python
"""대안 변동성 필터 검증: atr14_pct 상위 decile 제외 효과 (rv20_pct와 비교)"""

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

def main():
    print("Loading data...")
    panel = pd.read_parquet(DATA, columns=["ticker", "date", "fwd_d20", "fwd_d60", "fwd_d120"])
    wanted = set(pd.read_parquet(DATA, columns=['ticker'])['ticker'].unique())
    
    from liquidity_factor_study import load_full_ohlc, features_from_ohlc
    full, stream_stats = load_full_ohlc(set(pd.read_parquet(DATA, columns=['ticker'])['ticker'].unique()))
    frames = []
    for t, rows in full.items():
        f = features_from_ohlc(rows)
        f.insert(0, "ticker", t)
        frames.append(f)
    feats = pd.concat(frames, ignore_index=True)

    df = panel.merge(feats, on=["ticker", "date"], how="inner")
    for h in (20, 60, 120):
        df[f"fwd_d{h}"] = df[f"fwd_d{h}_x"]
    df = df.drop(columns=[c for c in df.columns if c.endswith("_x") or c.endswith("_y")])

    # Add deciles for rv20_pct, atr14_pct
    for feat, col in [("rv20_pct", "rv20_decile"), ("atr14_pct", "atr14_decile")]:
        def _q(grp):
            if len(grp) < 30:
                grp[col] = np.nan
                return grp
            grp[col] = pd.qcut(grp[feat].rank(method="first"), 10, labels=False) + 1
            return grp
        dec = df.dropna(subset=[feat]).groupby("date", group_keys=False).apply(_q)
        df = df.merge(dec[["ticker", "date", col]], on=["ticker", "date"], how="left")

    # mom60, mom20 deciles
    for feat, col in [("mom60", "mom60_decile"), ("mom20", "mom20_decile")]:
        def _q(grp):
            if len(grp) < 30:
                grp[col] = np.nan
                return grp
            grp[col] = pd.qcut(grp[feat].rank(method="first"), 10, labels=False) + 1
            return grp
        dec = df.dropna(subset=[feat]).groupby("date", group_keys=False).apply(_q)
        df = df.merge(dec[["ticker", "date", col]], on=["ticker", "date"], how="left")

    from liquidity_factor_study import monthly_rebalance_dates
    all_dates = pd.read_parquet(DATA, columns=['date'])['date'].unique()
    rebal = set(monthly_rebalance_dates(all_dates))
    rb = df[df["date"].isin(rebal)].copy()

    rb["dv20"] = np.exp(rb["dv20_log"])
    rb["gate_liq"] = rb["dv20"] >= 1e8
    rb["gate_price"] = rb["close"] >= 5000.0

    vol_cols = ["rv20_decile", "atr14_decile"]
    
    print("\n=== 변동성 필터별 게이트 C 효과 (d60 바스켓 Gross) ===")
    for vol_col in vol_cols:
        rb[f"gate_vol_{vol_col}"] = rb[vol_col] != 10
        
        arms = {
            "A_full": pd.Series(True, index=rb.index),
            "B_liq": rb["gate_liq"],
            "C_vol_excl": rb["gate_liq"] & (rb[vol_col] != 10),
            "D_full": rb["gate_liq"] & (rb[vol_col] != 10) & (rb["close"] >= 5000),
        }
        
        print(f"\n=== {vol_col} 상위 decile 제외 효과 ===")
        for arm_name, mask in arms.items():
            sub = rb[mask.fillna(False)]
            for sig_name, feat in [("LOWMOM60", "mom60"), ("REV20", "mom20")]:
                sub_valid = sub.dropna(subset=[feat])
                if len(sub_valid) == 0:
                    continue
                bsk = []
                for d, gd in sub_valid.groupby("date"):
                    gg = gd.dropna(subset=[feat, "fwd_d60"])
                    if len(gg) < 30:
                        continue
                    dec = pd.qcut(gg[feat].rank(method="first"), 10, labels=False).to_numpy() + 1
                    bot = gg.loc[dec == 1, "fwd_d60"]
                    if len(bot):
                        bsk.append(float(bot.mean()))
                if bsk:
                    mean_bsk = np.mean(bsk)
                    print(f"  {arm_name} | {sig_name}: basket fwd_d60 = {np.mean(bsk):+.4f}")

if __name__ == "__main__":
    main()