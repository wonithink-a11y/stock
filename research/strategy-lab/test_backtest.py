#!/usr/bin/env python
"""Test backtest loop logic step by step."""
import pandas as pd
import numpy as np
from pathlib import Path

p = Path(r'C:\Users\User\projects\stock\research\strategy-lab\data\crypto\basis\1h\BTCUSDT_1h.parquet')
h1 = pd.read_parquet(r'C:\Users\User\projects\stock\research\strategy-lab\data\crypto\basis\1h\BTCUSDT_1h.parquet')
h1['kst_date'] = (h1['time'] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
g = h1.groupby('kst_date')
daily = pd.DataFrame({
    'close': g['mark_close'].last(),
    'high': g['mark_high'].max(),
    'low': g['mark_low'].min(),
    'open': g['mark_open'].first(),
})
daily.index.name = 'date'

c = daily['close']
for w in [9, 21, 50, 200, 20, 60, 120]:
    daily[f'ema_{w}'] = c.ewm(span=w).mean()
daily['mom30'] = c.pct_change(30)
daily['mom_60'] = c.pct_change(60)
daily['btc_regime'] = np.where(c.pct_change(30) > 0, 'bull', 'bear')
daily['atr_14'] = (daily['high'] - daily['low']).rolling(14).mean()

daily = daily[(daily.index >= pd.Timestamp('2025-01-01')) & (daily.index <= pd.Timestamp('2026-08-28'))]

sig = pd.Series(0, index=daily.index)
sig[(daily['mom30'] > 0) & (daily['mom_60'] > 0)] = 1
sig[(daily['mom30'] < 0) | (daily['mom_60'] < 0)] = -1
signal = sig
position = sig.replace({-1: 0}).ffill().fillna(0).astype(int)
position = position * (daily['mom30'] > 0).astype(int)
daily['position'] = position

c = daily['close']
h = daily['high']
l = daily['low']
atr = (h - l).rolling(14).mean()
mom30 = c.pct_change(30)
mom60 = c.pct_change(60)

# Test first 50 days
in_pos = False
entry_px = np.nan
trailing_high = np.nan
rets = []
in_pos = False
entry_px = np.nan
trailing_high = np.nan
rets = []

for i in range(min(50, len(daily))):
    target_pos = 1 if daily['position'].iloc[i] == 1 else 0
    
    if True and daily['mom30'].iloc[i] <= 0:
        target_pos = 0
    
    print(f'Day {i}: in_pos={in_pos}, target_pos={target_pos}, pos={daily["position"].iloc[i]}')
    
    if not in_pos and target_pos == 1:
        in_pos = True
        entry_px = daily['close'].iloc[i]
        trailing_high = daily['high'].iloc[i]
        print(f'  Day {i}: ENTRY at {daily["close"].iloc[i]:.2f}')
        rets.append(-0.0005)
    elif in_pos and target_pos == 0:
        ret = daily['close'].iloc[i] / entry_px - 1 if entry_px > 0 else 0
        print(f'  Day {i}: EXIT at {daily["close"].iloc[i]:.2f}, ret={ret:.4f}')
        rets.append(ret - 0.0005)
        in_pos = False
        entry_px = np.nan
    elif in_pos:
        if entry_px > 0:
            ret = daily['close'].iloc[i] / entry_px - 1
            exited = False
            
            if ret <= -0.05:
                exited = True
                print(f'  Day {i}: STOP LOSS hit, ret={ret:.4f}')
            elif not np.isnan(daily['atr_14'].iloc[i]) and daily['atr_14'].iloc[i] > 0:
                atr_stop = 2.0 * daily['atr_14'].iloc[i] / daily['close'].iloc[i]
                if ret <= -atr_stop:
                    exited = True
                    print(f'  Day {i}: ATR STOP hit, ret={ret:.4f}')
            elif ret >= 999:
                exited = True
            elif 0.05 > 0:
                if np.isnan(trailing_high) or daily['high'].iloc[i] > trailing_high:
                    trailing_high = daily['high'].iloc[i]
                trail_px = trailing_high * (1 - 0.05)
                if daily['low'].iloc[i] <= trail_px:
                    exited = True
                    print(f'  Day {i}: TRAIL STOP hit, ret={ret:.4f}')
            
            if exited:
                ret = daily['close'].iloc[i] / entry_px - 1 if entry_px > 0 else 0
                rets.append(ret - 0.0005)
                in_pos = False
                entry_px = np.nan
            else:
                pass
    
    position = 1 if in_pos else 0

print('Total returns:', len(rets))
print('Returns:', rets[:5] if rets else 'None')