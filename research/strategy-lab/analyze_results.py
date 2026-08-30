#!/usr/bin/env python
"""Quick diagnostic of the backtest results"""

import json
import os
import pandas as pd
import numpy as np

# Load results
with open(r'C:\Users\User\projects\stock\research\strategy-lab\reports\regime_comparison_20260828\comparison.json') as f:
    comp = json.load(f)

mat = comp['materials']
reg = comp['regime']

print("=== DETAILED METRICS COMPARISON ===")
print()

# 1. Basic metrics
print("1. CORE METRICS")
print("-" * 60)
for k in ['total_return', 'cagr', 'mdd', 'sharpe', 'sortino', 'calmar', 'winrate', 'volatility']:
    v1 = mat.get(k, 0)
    v2 = reg.get(k, 0)
    diff = v2 - v1
    if k == 'mdd':
        diff = v2 - v1  # less negative is better
    print(f"  {k:15s}: Materials={v1:.4f}, Regime={v2:.4f}, Diff={diff:+.4f}")

# 2. Load equity curves for deeper analysis
eq1 = pd.read_parquet(r'C:\Users\User\projects\stock\research\strategy-lab\reports\regime_comparison_20260828\materials_equity.parquet')
eq2 = pd.read_parquet(r'C:\Users\User\projects\stock\research\strategy-lab\reports\regime_comparison_20260828\regime_equity.parquet')

print(f"\nEquity curve shapes: Mat={eq1.shape}, Reg={eq2.shape}")
print(f"Date range: {eq1.index[0]} to {eq1.index[-1]}")

# Align dates
common = eq1.index.intersection(eq2.index)
eq1_a = eq1.loc[common]
eq2_a = eq2.loc[common]

# Monthly returns
m1 = eq1_a['portfolio_value'].resample('M').last().pct_change().dropna()
m2 = eq2_a['portfolio_value'].resample('M').last().pct_change().dropna()

print(f"\nMonthly return stats:")
print(f"  Materials: mean={m1.mean():.4f}, std={m1.std():.4f}, skew={m1.skew():.4f}")
print(f"  Regime:    mean={m2.mean():.4f}, std={m2.std():.4f}, skew={m2.skew():.4f}")

# Rolling 12M returns
r12_1 = eq1_a['portfolio_value'].pct_change(12).dropna()
r12_2 = eq2_a['portfolio_value'].pct_change(12).dropna()
print(f"\nRolling 12M return stats:")
print(f"  Materials: mean={r12_1.mean():.4f}, std={r12_1.std():.4f}")
print(f"  Regime:    mean={r12_2.mean():.4f}, std={r12_2.std():.4f}")

# Drawdown analysis
def get_dd_stats(eq):
    cum = eq['portfolio_value']
    running_max = cum.cummax()
    dd = (cum / cum.cummax() - 1)
    return {
        'max_dd': dd.min(),
        'avg_dd': dd[dd < 0].mean(),
        'dd_duration': (dd < -0.05).sum() / len(dd) * 100  # % time in >5% DD
    }

print(f"\nDrawdown analysis:")
for name, eq in [('Materials', pd.read_parquet(r'C:\Users\User\projects\stock\research\strategy-lab\reports\regime_comparison_20260828\materials_equity.parquet')),
                  ('Regime', pd.read_parquet(r'C:\Users\User\projects\stock\research\strategy-lab\reports\regime_comparison_20260828\regime_equity.parquet'))]:
    stats = get_dd_stats(eq)
    print(f"  {name}: MaxDD={stats['max_dd']:.2%}, AvgDD={stats['avg_dd']:.2%}, Time>5% DD={stats['dd_duration']:.1f}%")

# Yearly returns
print("\nYearly returns:")
for name, eq in [('Materials', pd.read_parquet(r'C:\Users\User\projects\stock\research\strategy-lab\reports\regime_comparison_20260828\materials_equity.parquet')),
                  ('Regime', pd.read_parquet(r'C:\Users\User\projects\stock\research\strategy-lab\reports\regime_comparison_20260828\regime_equity.parquet'))]:
    yearly = eq['portfolio_value'].resample('Y').last().pct_change().dropna()
    print(f"\n{name}:")
    for y, r in yearly.items():
        print(f"  {y.year}: {r:+.2%}")

# Correlation
common_dates = r12_1.index.intersection(r12_2.index)
r12_1a = r12_1.loc[common_dates]
r12_2a = r12_2.loc[common_dates]
corr = np.corrcoef(r12_1a, r12_2a)[0,1]
print(f"\nRolling 12M correlation: {corr:.4f}")

# Weight analysis
w1 = pd.read_parquet(r'C:\Users\User\projects\stock\research\strategy-lab\reports\regime_comparison_20260828\materials_weights.parquet')
w2 = pd.read_parquet(r'C:\Users\User\projects\stock\reports\regime_comparison_20260828\regime_weights.parquet')

print(f"\nAverage weights:")
for name, w in [('Materials', w1), ('Regime', w2)]:
    asset_cols = [c for c in w.columns if not c.startswith('w_')]
    if asset_cols:
        avg_w = w[asset_cols].mean()
        print(f"\n{name} avg weights:")
        for a, w in avg_w.sort_values(ascending=False).items():
            print(f"  {a}: {w:.2%}")