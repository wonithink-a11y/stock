#!/usr/bin/env python
"""게이트 검증: 핵심 지표만 빠르게 계산 (최적화 버전)"""

import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from liquidity_factor_study import (
    DATA, REPO_ROOT,
    load_full_ohlc, features_from_ohlc,
    monthly_rebalance_dates, LIQ_THRESHOLD,
)

def load_data():
    """데이터 로드 (캐싱된 게이트 결과 활용)"""
    with open(r'C:\Users\User\projects\stock\research\strategy-lab\reports\2026-08-26-universe-gate\gate-results.json') as f:
        gate_results = json.load(f)
    
    panel = pd.read_parquet(DATA, columns=["ticker", "date", "fwd_d20", "fwd_d60", "fwd_d120"])
    wanted = set(pd.read_parquet(DATA, columns=['ticker'])['ticker'].unique())
    
    from liquidity_factor_study import load_full_ohlc, features_from_ohlc
    full, _ = load_full_ohlc(wanted)
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

    # rv20, atr14 deciles
    for feat, col in [("rv20_pct", "rv20_decile"), ("atr14_pct", "atr14_decile")]:
        def _q(grp):
            if len(grp) < 30:
                grp[col] = np.nan
                return grp
            grp[col] = pd.qcut(grp[feat].rank(method="first"), 10, labels=False) + 1
            return grp
        dec = df.dropna(subset=[feat]).groupby("date", group_keys=False).apply(
            lambda g: g.assign(**{col: pd.qcut(g[feat].rank(method="first"), 10, labels=False)+1}) if len(g)>=30 else g.assign(**{col: np.nan})
        )
        df = df.merge(dec[["ticker", "date", col]], on=["ticker", "date"], how="left")

    # mom60, mom20 deciles
    for feat, col in [("mom60", "mom60_decile"), ("mom20", "mom20_decile")]:
        dec = df.dropna(subset=[feat]).groupby("date", group_keys=False).apply(
            lambda g: g.assign(**{col: pd.qcut(g[feat].rank(method="first"), 10, labels=False)+1}) if len(g)>=30 else g.assign(**{col: np.nan})
        )
        df = df.merge(dec[["ticker", "date", col]], on=["ticker", "date"], how="left")

    from liquidity_factor_study import monthly_rebalance_dates
    all_dates = pd.read_parquet(DATA, columns=['date'])['date'].unique()
    rebal = set(monthly_rebalance_dates(all_dates))
    rb = df[df["date"].isin(rebal)].copy()

    rb["dv20"] = np.exp(rb["dv20_log"])
    rb["gate_liq"] = rb["dv20"] >= 1e8
    rb["gate_price"] = rb["close"] >= 5000.0
    rb["gate_rv_excl"] = rb["rv20_decile"] != 10
    rb["gate_atr_excl"] = rb["atr14_decile"] != 10
    
    return rb, sorted(rebal)

def analyze_arm(rb, arm_name, mask_fn, feat, rebal_dates):
    """단일 arm에 대한 분석"""
    sub = rb[mask_fn(rb)].copy()
    
    # 월별 데이터 수집
    spreads = []
    basket_rets = []
    monthly_counts = []
    
    for d in rebal:
        sub_d = sub[sub["date"] == d].dropna(subset=[feat])
        if len(sub_d) < 30:
            continue
            
        monthly_counts.append(len(sub_d))
        
        # Spread
        gg = sub_d.dropna(subset=[feat, "fwd_d60"])
        if len(gg) >= 30:
            dec = pd.qcut(gg[feat].rank(method="first"), 10, labels=False).to_numpy() + 1
            vals = gg["fwd_d60"].to_numpy()
            top, bot = vals[dec == 10], vals[dec == 1]
            if len(top) and len(bot):
                spreads.append(float(bot.mean() - top.mean()))
        
        # Basket return
        dec = pd.qcut(sub_d[feat].rank(method="first"), 10, labels=False) + 1
        bot = sub_d[dec == 1]
        if len(bot):
            fwd = bot["fwd_d60"].mean()
            if not np.isnan(fwd):
                return {"spread": np.array(spreads) if spreads else np.array([])}
    
    return {"spread": np.array([])}

def main():
    rb, rebal = load_data()
    
    gates = {
        "A_full": lambda df: pd.Series(True, index=df.index),
        "B_liq1e8": lambda df: df["dv20"] >= 1e8,
        "C_rv_excl": lambda df: (df["dv20"] >= 1e8) & (df["rv20_decile"] != 10),
        "C_atr_excl": lambda df: (df["dv20"] >= 1e8) & (df["atr14_decile"] != 10),
        "D_rv_price": lambda df: (df["dv20"] >= 1e8) & (df["rv20_decile"] != 10) & (df["close"] >= 5000),
        "D_atr_price": lambda df: (df["dv20"] >= 1e8) & (df["atr14_decile"] != 10) & (df["close"] >= 5000),
        "B_atr_excl": lambda df: (df["dv20"] >= 1e8) & (df["atr14_decile"] != 10),
    }
    
    from liquidity_factor_study import monthly_rebalance_dates
    all_dates = pd.read_parquet(DATA, columns=['date'])['date'].unique()
    rebal = sorted(set(monthly_rebalance_dates(pd.read_parquet(DATA, columns=['date'])['date'].unique())))
    
    print("="*80)
    print("GATE VALIDATION: 종합 분석")
    print("="*80)
    
    for sig_name, feat in [("LOWMOM60", "mom60"), ("REV20", "mom20")]:
        print(f"\n{'='*60}")
        print(f"=== {sig_name} ({feat}) ===")
        print(f"{'='*60}")
        
        for arm_name in ["A_full", "B_liq1e8", "C_rv_excl", "C_atr_excl",
                         "D_rv_price", "D_atr_price", "B_atr_excl"]:
            mask = gates[arm_name](rb) if arm_name != "A_full" else pd.Series(True, index=rb.index)
            sub = rb[mask].dropna(subset=[feat, "fwd_d60"])
            if len(sub) < 30:
                print(f"  {arm_name}: insufficient data")
                continue
            
            # Monthly spread
            spreads = []
            for d, gd in sub.groupby("date"):
                if len(gd) < 30:
                    continue
                gg = gd.dropna(subset=[feat, "fwd_d60"])
                if len(gg) < 30:
                    continue
                dec = pd.qcut(gg[feat].rank(method="first"), 10, labels=False) + 1
                vals = gg["fwd_d60"].to_numpy()
                top, bot = vals[dec == 10], vals[dec == 1]
                if len(top) and len(bot):
                    spreads.append(float(bot.mean() - top.mean()))
            
            if spreads:
                sp = np.array(spreads)
                from liquidity_factor_study import newey_west_t
                print(f"  {arm_name:20s} | spread: {np.mean(spreads):+.4f} (NWT: {newey_west_t(sp, 3):+.2f}, n={len(spreads)})")
    
    print("\n=== 분석 완료 ===")

if __name__ == "__main__":
    main()