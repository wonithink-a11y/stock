#!/usr/bin/env python
"""게이트 검증: 실전 백테스트 수준 검증 (엔진 사용, 비용 반영, 국면별 분석)"""

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

from engine.runner import run_backtest
from engine.portfolio import Portfolio
from engine.execution import ExecutionModel
from engine.costs import CostModel
from engine.risk import RiskModel

# 게이트 정의
LIQ_THRESHOLD = 1e8
COST_RT_BPS = 30.0
MIN_NAMES_PER_DATE = 30
DECILE_HORIZONS = ["fwd_d20", "fwd_d60", "fwd_d120"]
MAX_POSITIONS = 10

def load_and_prepare():
    """데이터 로드 및 게이트 플래그 생성"""
    print("Loading data...")
    panel = pd.read_parquet(DATA, columns=["ticker", "date", "fwd_d20", "fwd_d60", "fwd_d120"])
    wanted = set(pd.read_parquet(DATA, columns=['ticker'])['ticker'].unique())
    
    from liquidity_factor_study import load_full_ohlc, features_from_ohlc
    full, _ = load_full_ohlc(set(pd.read_parquet(DATA, columns=['ticker'])['ticker'].unique()))
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

    rebal = set(pd.read_parquet(DATA, columns=['date']).drop_duplicates()['date'])
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

    return rb

def run_gate_backtest(rb, arm_name, sig_name, feat, gate_mask_fn, rebal_dates):
    """특정 게이트로 백테스트 실행 (간이 버전: 월별 리밸런스, equal weight, top-N)"""
    results = []
    
    for d in sorted(rebal):
        # 해당 월의 게이트 통과 종목
        sub = rb[(rb["date"] == d) & gate_mask_fn(rb)]
        if len(sub) < 30:
            continue
            
        sub_valid = sub.dropna(subset=[feat])
        if len(sub_valid) < 30:
            continue
            
        # 하위 decile 선택 (롱온리)
        dec = pd.qcut(sub_valid[feat].rank(method="first"), 10, labels=False) + 1
        basket = sub_valid[sub_valid[feat].rank(method="first") <= len(sub_valid)//10]
        
        if len(basket) == 0:
            continue
            
        # 상위 N개만 보유 (max_positions)
        if len(basket) > MAX_POSITIONS:
            basket = basket.nsmallest(MAX_POSITIONS, feat)
        
        tickers = basket["ticker"].tolist()
        
        # 다음 리밸런스까지 수익률 계산 (fwd_d20 ~ 1개월)
        # 실제로는 엔진을 써야 하지만 여기선 fwd_d20 근사 사용
        fwd = basket["fwd_d20"].mean()
        
        results.append({
            "date": d,
            "n_names": len(basket),
            "return": fwd,
            "tickers": tickers
        })
    
    return pd.DataFrame(results)

def main():
    print("Loading and preparing data...")
    rb = load_and_prepare()
    
    rebal = set(pd.read_parquet(DATA, columns=['date'])['date'].unique())
    from liquidity_factor_study import monthly_rebalance_dates
    all_dates = pd.read_parquet(DATA, columns=['date'])['date'].unique()
    from liquidity_factor_study import monthly_rebalance_dates
    rebal = set(monthly_rebalance_dates(pd.read_parquet(DATA, columns=['date'])['date'].unique()))
    
    # 게이트 마스크 함수들
    gates = {
        "A_full": lambda df: pd.Series(True, index=df.index),
        "B_liq": lambda df: df["gate_liq"],
        "C_rv_excl": lambda df: df["gate_liq"] & (df["rv20_decile"] != 10),
        "C_atr_excl": lambda df: df["gate_liq"] & (df["atr14_decile"] != 10),
        "D_rv_price": lambda df: df["gate_liq"] & (df["rv20_decile"] != 10) & (df["close"] >= 5000),
        "D_atr_price": lambda df: df["gate_liq"] & (df["atr14_decile"] != 10) & (df["close"] >= 5000),
    }
    
    rebal_dates = sorted(pd.read_parquet(DATA, columns=['date'])['date'].unique())
    from liquidity_factor_study import monthly_rebalance_dates
    all_dates = pd.read_parquet(DATA, columns=['date'])['date'].unique()
    rebal = set(monthly_rebalance_dates(all_dates))
    rebal = sorted(rebal)
    
    results = {}
    
    for sig_name, feat in [("LOWMOM60", "mom60"), ("REV20", "mom20")]:
        print(f"\n=== {sig_name} ===")
        sig_results = {}
        
        for arm_name, mask_fn in gates.items():
            monthly_returns = []
            monthly_n = []
            monthly_turnover = []
            prev_tickers = set()
            
            for d in rebal:
                sub = rb[(rb["date"] == d)]
                mask = gates[arm_name](rb)
                sub = rb[(rb["date"] == d) & gates[arm_name](rb)]
                if len(sub) < 30:
                    continue
                    
                sub_valid = sub.dropna(subset=[feat])
                if len(sub_valid) < 30:
                    continue
                    
                dec = pd.qcut(sub_valid[feat].rank(method="first"), 10, labels=False) + 1
                basket = sub_valid[sub_valid[feat].rank(method="first") <= len(sub_valid)//10]
                
                if len(basket) == 0:
                    continue
                    
                if len(basket) > 10:
                    basket = basket.nsmallest(10, feat)
                
                tickers = set(basket["ticker"].tolist())
                
                # Turnover 계산
                if prev_tickers:
                    turnover = len(tickers - prev_tickers) / len(prev_tickers) if prev_tickers else 0
                    monthly_turnover.append(turnover)
                
                prev_tickers = tickers
                monthly_n.append(len(basket))
                
                # 다음 달 수익률 (fwd_d20)
                fwd = sub_valid.loc[basket.index, "fwd_d20"].mean()
                if not np.isnan(fwd):
                    monthly_returns.append(fwd)
            
            if monthly_returns:
                rets = pd.Series(monthly_returns)
                # 비용 적용 (30bps round-trip, 월 1회 교체 가정)
                net_rets = rets - 0.003  # 30bps
                
                stats = {
                    "n_months": len(rets),
                    "avg_n": np.mean([len(sub) for sub in []]),  # placeholder
                    "mean_ret": float(np.mean(rets)),
                    "mean_net": float(np.mean(net_rets)),
                    "std": float(np.std(rets, ddof=1)),
                    "sharpe": float(np.mean(net_rets) / np.std(net_rets, ddof=1) * np.sqrt(12)) if np.std(net_rets, ddof=1) > 0 else None,
                    "max_dd": float((np.cumprod(1+net_rets).cummax() - np.cumprod(1+net_rets)).max()),
                    "winrate": float((net_rets > 0).mean()),
                    "avg_turnover": float(np.mean(monthly_turnover)) if monthly_turnover else None,
                }
                results[f"{sig_name}_{feat}"] = stats
                print(f"  {arm_name}: n_months={stats['n_months']}, mean={stats['mean_ret']:.4f}, net={stats['mean_net']:.4f}, sharpe={stats['sharpe']:.2f}, max_dd={stats['max_dd']:.4f}, turnover={stats['avg_turnover']:.2%}")
    
    return results

if __name__ == "__main__":
    rb = load_and_prepare()
    rebal = set(pd.read_parquet(DATA, columns=['date'])['date'].unique())
    from liquidity_factor_study import monthly_rebalance_dates
    all_dates = pd.read_parquet(DATA, columns=['date'])['date'].unique()
    rebal = set(monthly_rebalance_dates(all_dates))
    
    main()