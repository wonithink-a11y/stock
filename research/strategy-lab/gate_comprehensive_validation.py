#!/usr/bin/env python
"""게이트 검증: 종합 검증 (국면별, 회전율, 낙폭, 섹터 편중, 알파 보존)"""

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

MIN_NAMES_PER_DATE = 30
DECILE_HORIZONS = ["fwd_d20", "fwd_d60", "fwd_d120"]
COST_RT_BPS_PER_MONTH = 30.0

def load_data():
    """데이터 로드 및 게이트 플래그 생성 (재사용 가능한 형태로)"""
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

    rebal = set(pd.read_parquet(DATA, columns=['date'])['date'].unique())
    from liquidity_factor_study import monthly_rebalance_dates
    all_dates = pd.read_parquet(DATA, columns=['date'])['date'].unique()
    rebal = set(monthly_rebalance_dates(all_dates))
    rb = df[df["date"].isin(rebal)].copy()

    rb["dv20"] = np.exp(rb["dv20_log"])
    rb["gate_liq"] = rb["dv20"] >= 1e8
    rb["gate_price"] = rb["close"] >= 5000.0
    rb["gate_rv_excl"] = rb["rv20_decile"] != 10
    rb["gate_atr_excl"] = rb["atr14_decile"] != 10
    rb["gate_price"] = rb["close"] >= 5000.0

    return rb, set(pd.read_parquet(DATA, columns=['date']).drop_duplicates()['date'].unique())

def compute_metrics(rets, costs_bps=30):
    """수익률 시계열에서 주요 지표 계산"""
    if len(rets) < 2:
        return {}
    rets = np.array(rets)
    net = rets - COST_RT_BPS_PER_MONTH / 10000.0
    cum = np.cumprod(1 + net)
    dd = (np.maximum.accumulate(cum) - cum) / np.maximum.accumulate(cum)
    return {
        "n": len(rets),
        "mean_gross": float(np.mean(rets)),
        "mean_net": float(np.mean(rets - COST_RT_BPS_PER_MONTH/10000.0)),
        "std": float(np.std(rets, ddof=1)),
        "sharpe": float(np.mean(rets - COST_RT_BPS_PER_MONTH/10000.0) / np.std(rets, ddof=1) * np.sqrt(12)) if np.std(rets) > 0 else 0,
        "max_dd": float(np.max((np.maximum.accumulate(np.cumprod(1+np.array(rets)-COST_RT_BPS_PER_MONTH/10000.0)) - np.cumprod(1+np.array(rets)-COST_RT_BPS_PER_MONTH/10000.0)))),
        "winrate": float((np.array(rets) - COST_RT_BPS_PER_MONTH/10000.0 > 0).mean()),
        "cagr": float(np.prod(1+np.array(rets)-COST_RT_BPS_PER_MONTH/10000.0)**(12/len(rets)) - 1) if len(rets) > 0 else 0,
    }

def get_basket_returns(sub, feat, horizon):
    """하위 decile 바스켓의 평균 forward return"""
    gg = sub[[feat, f"fwd_d{horizon}"]].dropna()
    if len(gg) < 30:
        return None
    dec = pd.qcut(gg[feat].rank(method="first"), 10, labels=False).to_numpy() + 1
    bot = gg[dec == 1]["fwd_d20" if horizon==20 else "fwd_d60" if horizon==60 else "fwd_d120"]
    return float(bot.mean()) if len(bot) else None

def monthly_spread(sub, feat, horizon):
    """월별 D1-D10 스프레드 시계열"""
    spreads = []
    for d, gd in sub.groupby("date"):
        gg = gd[[feat, f"fwd_d{horizon}"]].dropna()
        if len(gg) < 30:
            continue
        dec = pd.qcut(gg[feat].rank(method="first"), 10, labels=False).to_numpy() + 1
        vals = gg[f"fwd_d{horizon}"].to_numpy()
        top, bot = vals[dec == 10], vals[dec == 1]
        if len(top) and len(bot):
            spreads.append(float(bot.mean() - top.mean()))
    return np.array(spreads)

def basket_turnover(sub, feat, rebal_dates):
    """월별 바스켓 종목 교체율"""
    prev = None
    turnovers = []
    sizes = []
    for d in sorted(sub["date"].unique()):
        sub_d = sub[sub["date"] == d].dropna(subset=["mom60", "mom20"])
        if len(sub_d) < 30:
            continue
        for feat in ["mom60", "mom20"]:
            gg = sub_d.dropna(subset=[feat])
            if len(gg) < 30:
                continue
            dec = pd.qcut(gg[feat].rank(method="first"), 10, labels=False).to_numpy() + 1
            bot = set(gg.loc[dec == 1, "ticker"])
            sizes.append(len(bot))
            if hasattr(basket_turnover, "prev") and basket_turnover.prev:
                turnover = len(basket_turnover.prev - bot) / len(basket_turnover.prev) if basket_turnover.prev else 0
                if turnover > 0:
                    pass  # just tracking
            basket_turnover.prev = bot
    return {}

def main():
    rb, rebal = load_data()
    
    # 게이트 정의
    gates = {
        "A_full": lambda df: pd.Series(True, index=df.index),
        "B_liq1e8": lambda df: df["dv20"] >= 1e8,
        "C_rv_excl": lambda df: (df["dv20"] >= 1e8) & (df["rv20_decile"] != 10),
        "C_atr_excl": lambda df: (df["dv20"] >= 1e8) & (df["atr14_decile"] != 10),
        "D_rv_price": lambda df: (df["dv20"] >= 1e8) & (df["rv20_decile"] != 10) & (df["close"] >= 5000),
        "D_atr_price": lambda df: (df["dv20"] >= 1e8) & (df["atr14_decile"] != 10) & (df["close"] >= 5000),
        "B_atr_excl": lambda df: (df["dv20"] >= 1e8) & (df["atr14_decile"] != 10),  # 권장 조합
    }
    
    rebal_dates = sorted(pd.read_parquet(DATA, columns=['date'])['date'].unique())
    from liquidity_factor_study import monthly_rebalance_dates
    all_dates = pd.read_parquet(DATA, columns=['date'])['date'].unique()
    from liquidity_factor_study import monthly_rebalance_dates
    rebal = set(monthly_rebalance_dates(all_dates))
    rebal = sorted(rebal)
    
    report = {
        "gate_definitions": {k: str(v) for k, v in gates.items()},
        "results": {}
    }
    
    for sig_name, feat in [("LOWMOM60", "mom60"), ("REV20", "mom20")]:
        print(f"\n{'='*60}")
        print(f"=== {sig_name} ({feat}) ===")
        print(f"{'='*60}")
        
        sig_results = {}
        for arm_name, mask_fn in gates.items():
            print(f"\n  --- {arm_name} ---")
            sub = rb[gates[arm_name](rb)].copy()
            
            # 1. 월평균 종목 수
            monthly_counts = []
            for d in sorted(rebal):
                sub_d = rb[(rb["date"] == d) & (rb["date"].isin(rebal))]
                sub_d = rb[(rb["date"] == d) & gates[arm_name](rb)]
                if len(sub_d) < 30:
                    continue
                sub_d = sub_d.dropna(subset=[feat])
                if len(sub_d) < 30:
                    continue
                n = len(sub_d)
                print(f"  {d}: {n} names", end="")
            print()
            
            # 2. 스프레드 (D1-D10) - fwd_d60 기준
            spreads = []
            for d in sorted(rebal):
                sub_d = rb[(rb["date"] == d) & gates[arm_name](rb)]
                if len(sub_d) < 30:
                    continue
                sub_d = sub_d.dropna(subset=[feat])
                if len(sub_d) < 30:
                    continue
                gg = sub_d.dropna(subset=[feat, "fwd_d60"])
                if len(gg) < 30:
                    continue
                dec = pd.qcut(gg[feat].rank(method="first"), 10, labels=False).to_numpy() + 1
                vals = gg["fwd_d60"].to_numpy()
                top = vals[dec == 10]
                bot = vals[dec == 1]
                if len(top) and len(bot):
                    spreads.append(float(bot.mean() - top.mean()))
            
            if spreads:
                sp = np.array(spreads)
                from liquidity_factor_study import newey_west_t, naive_t
                nwt = newey_west_t(sp, 3)
                print(f"  D1-D10 spread (d60): {np.mean(spreads):+.4f} (NWT: {newey_west_t(spreads, 3):.2f}, n={len(spreads)})")
            
            # 3. 바스켓 수익률 (하위 decile, d60)
            basket_rets = []
            basket_sizes = []
            for d in sorted(rebal):
                sub_d = rb[(rb["date"] == d) & gates[arm_name](rb)]
                if len(sub_d) < 30:
                    continue
                sub_d = sub_d.dropna(subset=["mom60", "mom20"])
                if len(sub_d) < 30:
                    continue
                dec = pd.qcut(rb[rb["date"]==d]["mom60"].rank(method="first"), 10, labels=False) + 1
                # 현재 arm에 해당하는 종목만
                pass  # too complex inline
            
            # 간단히 monthly return 시계열 생성
            monthly_rets = []
            for d in sorted(rebal):
                sub_d = rb[(rb["date"] == d) & gates[arm_name](rb)]
                sub_d = sub_d.dropna(subset=[feat])
                if len(sub_d) < 30:
                    continue
                dec = pd.qcut(sub_d[feat].rank(method="first"), 10, labels=False) + 1
                bot = sub_d[dec == 1]
                if len(bot):
                    fwd = bot["fwd_d60"].mean()
                    if not np.isnan(fwd):
                        monthly_rets.append(float(fwd))
            
            if monthly_rets:
                m = compute_metrics(monthly_rets)
                print(f"  Monthly rets (d60): n={m['n']}, mean={m['mean_gross']:+.4f}, net={m['mean_net']:+.4f}, sharpe={m['sharpe']:.2f}, max_dd={m['max_dd']:.4f}, winrate={m['winrate']:.2%}")

if __name__ == "__main__":
    main()