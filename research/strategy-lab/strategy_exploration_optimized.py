"""
Optimized Korean Market Strategy Exploration
Uses pre-converted Parquet for fast loading
"""
import sys
sys.path.insert(0, 'research/strategy-lab')

import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path

# ============================================================
# 1. DATA LOADING (from Parquet)
# ============================================================

def load_universe():
    tickers = []
    with open('data/backfill/universe/a1a/current.jsonl', 'r', encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            if r['market'] in ('KOSPI', 'KOSDAQ'):
                tickers.append(r['ticker'])
    return set(tickers)

def load_calendar():
    with open('data/backfill/calendar.json', 'r', encoding='utf-8') as f:
        cal = json.load(f)
    return cal['tradingDays']

def load_price_data_parquet(tickers, start_date='2016-01-01', end_date='2026-08-03'):
    """Load from pre-converted parquet files"""
    CACHE_DIR = Path("research/strategy-lab/.cache/a2a_parquet")
    tickers_set = set(tickers)
    
    all_dfs = []
    for year in range(2016, 2027):
        path = CACHE_DIR / f"{year}.parquet"
        if path.exists():
            df = pd.read_parquet(path)
            df = df[df['ticker'].isin(tickers_set)]
            if len(df) > 0:
                all_dfs.append(df)
    
    if not all_dfs:
        return {}
    
    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined[(combined['date'] >= start_date) & (combined['date'] <= end_date)]
    
    # Pivot to dict of DataFrames
    price_dict = {}
    for ticker, group in combined.groupby('ticker'):
        if len(group) >= 250:
            df = group.sort_values('date').set_index('date')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            price_dict[ticker] = df[['open', 'high', 'low', 'close', 'volume']]
    
    return price_dict

# ============================================================
# 2. SIGNAL COMPUTATION (vectorized per ticker)
# ============================================================

def compute_signals(df):
    signals = pd.DataFrame(index=df.index)
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    # Returns
    signals['ret_1d'] = close.pct_change()
    signals['ret_5d'] = close.pct_change(5)
    signals['ret_20d'] = close.pct_change(20)
    signals['ret_60d'] = close.pct_change(60)
    signals['ret_120d'] = close.pct_change(120)
    
    # Momentum
    signals['mom_1m'] = close.pct_change(20)
    signals['mom_3m'] = close.pct_change(60)
    signals['mom_6m'] = close.pct_change(120)
    signals['mom_12m'] = close.pct_change(240)
    
    # Risk-adjusted momentum
    vol_20d = signals['ret_1d'].rolling(20).std()
    signals['mom_3m_riskadj'] = signals['mom_3m'] / (vol_20d * np.sqrt(60) + 1e-8)
    signals['mom_6m_riskadj'] = signals['mom_6m'] / (vol_20d * np.sqrt(120) + 1e-8)
    
    # Breakout (Donchian)
    signals['donchian_20_high'] = high.rolling(20).max()
    signals['donchian_20_low'] = low.rolling(20).min()
    signals['breakout_20'] = (close - signals['donchian_20_low']) / (signals['donchian_20_high'] - signals['donchian_20_low'] + 1e-8)
    
    signals['donchian_60_high'] = high.rolling(60).max()
    signals['donchian_60_low'] = low.rolling(60).min()
    signals['breakout_60'] = (close - signals['donchian_60_low']) / (signals['donchian_60_high'] - signals['donchian_60_low'] + 1e-8)
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / (loss + 1e-8)
    signals['rsi_14'] = 100 - (100 / (1 + rs))
    
    # Pullback from high
    signals['dist_from_high_20'] = (signals['donchian_20_high'] - close) / close
    signals['dist_from_high_60'] = (signals['donchian_60_high'] - close) / close
    
    # Volume
    signals['volume_ma_20'] = volume.rolling(20).mean()
    signals['volume_ratio'] = volume / signals['volume_ma_20']
    
    # Volatility
    signals['vol_20d'] = signals['ret_1d'].rolling(20).std() * np.sqrt(252)
    
    # Moving averages
    signals['ma_5'] = close.rolling(5).mean()
    signals['ma_20'] = close.rolling(20).mean()
    signals['ma_60'] = close.rolling(60).mean()
    signals['ma_120'] = close.rolling(120).mean()
    signals['ma_5_20'] = close / signals['ma_5'] - 1
    signals['ma_20_60'] = signals['ma_20'] / signals['ma_60'] - 1
    signals['ma_60_120'] = signals['ma_60'] / signals['ma_120'] - 1
    
    # MACD
    signals['ema_12'] = close.ewm(span=12).mean()
    signals['ema_26'] = close.ewm(span=26).mean()
    signals['macd'] = signals['ema_12'] - signals['ema_26']
    signals['macd_signal'] = signals['macd'].ewm(span=9).mean()
    signals['macd_hist'] = signals['macd'] - signals['macd_signal']
    
    return signals

# ============================================================
# 3. DECILE BACKTEST (optimized)
# ============================================================

def run_decile_backtest(all_signals, price_data_dict, calendar, forward_days_list=[20, 60, 120]):
    cal_dates = pd.to_datetime(calendar)
    
    # Month-end dates
    month_ends = []
    for i in range(1, len(cal_dates)):
        if cal_dates[i].month != cal_dates[i-1].month:
            month_ends.append(cal_dates[i-1])
    if cal_dates[-1] not in month_ends:
        month_ends.append(cal_dates[-1])
    
    results = {}
    
    # Get signal names from first ticker
    first_ticker = next(iter(all_signals))
    signal_names = [c for c in all_signals[first_ticker].columns 
                    if c not in {'open', 'high', 'low', 'close', 'volume', 'ret_1d'}]
    
    print(f"Testing {len(signal_names)} signals across {len(month_ends)} rebalance dates...")
    
    for signal_name in signal_names:
        results[signal_name] = {}
        
        for fwd in forward_days_list:
            decile_returns = {d: [] for d in range(10)}
            
            for reb_date in month_ends:
                if reb_date not in cal_dates:
                    continue
                
                # Collect signals at rebalance date
                ticker_signals = []
                for ticker, sig_df in all_signals.items():
                    if signal_name in sig_df.columns:
                        try:
                            val = sig_df.loc[reb_date, signal_name]
                            if pd.notna(val):
                                ticker_signals.append((ticker, val))
                        except KeyError:
                            pass
                
                if len(ticker_signals) < 100:
                    continue
                
                ticker_signals.sort(key=lambda x: x[1])
                n = len(ticker_signals)
                decile_size = n // 10
                
                reb_idx = cal_dates.get_loc(reb_date)
                
                for d in range(10):
                    start_idx = d * decile_size
                    end_idx = (d + 1) * decile_size if d < 9 else n
                    decile_tickers = [ts[0] for ts in ticker_signals[start_idx:end_idx]]
                    
                    fwd_rets = []
                    for ticker in decile_tickers:
                        df = price_data_dict.get(ticker)
                        if df is not None:
                            fwd_idx = reb_idx + fwd
                            if fwd_idx < len(df):
                                entry_px = df.iloc[reb_idx]['close']
                                exit_px = df.iloc[fwd_idx]['close']
                                fwd_rets.append((exit_px - entry_px) / entry_px)
                    
                    if fwd_rets:
                        decile_returns[d].append(np.mean(fwd_rets))
            
            # Aggregate
            if any(len(v) > 0 for v in decile_returns.values()):
                avg_returns = [np.mean(decile_returns[d]) if decile_returns[d] else np.nan for d in range(10)]
                q1, q10 = avg_returns[0], avg_returns[9]
                spread = q10 - q1 if pd.notna(q1) and pd.notna(q10) else np.nan
                
                valid = [(i, r) for i, r in enumerate(avg_returns) if pd.notna(r)]
                monotonic = all(valid[i][1] <= valid[i+1][1] for i in range(len(valid)-1)) if len(valid) >= 2 else False
                
                spearman = np.nan
                if len(valid) == 10:
                    ranks = [v[0] for v in valid]
                    rets = [v[1] for v in valid]
                    spearman = np.corrcoef(ranks, rets)[0,1]
                
                results[signal_name][fwd] = {
                    'decile_returns': avg_returns,
                    'q10_q1_spread': spread,
                    'monotonic': monotonic,
                    'spearman_ic': spearman
                }
    
    return results

# ============================================================
# 4. MAIN
# ============================================================

def main():
    print("=" * 60)
    print("KOREAN MARKET STRATEGY EXPLORATION (2016-2026)")
    print("=" * 60)
    
    universe = load_universe()
    print(f"Universe: {len(universe)} tickers (KOSPI/KOSDAQ)")
    
    calendar = load_calendar()
    print(f"Calendar: {len(calendar)} trading days")
    
    print("\nLoading price data from Parquet...")
    price_data = load_price_data_parquet(universe)
    print(f"Loaded {len(price_data)} tickers with 250+ bars")
    
    print("\nComputing signals...")
    all_signals = {}
    for ticker, df in price_data.items():
        all_signals[ticker] = compute_signals(df)
    
    print(f"Computed signals for {len(all_signals)} tickers")
    
    print("\nRunning decile backtest...")
    results = run_decile_backtest(all_signals, price_data, calendar)
    
    # Print top signals
    print("\n" + "=" * 60)
    print("TOP SIGNALS BY Q10-Q1 SPREAD (60D FORWARD)")
    print("=" * 60)
    
    signal_scores = []
    for sig_name, fwd_dict in results.items():
        if 60 in fwd_dict:
            spread = fwd_dict[60].get('q10_q1_spread', np.nan)
            monotonic = fwd_dict[60].get('monotonic', False)
            spearman = fwd_dict[60].get('spearman_ic', np.nan)
            if pd.notna(spread):
                signal_scores.append((sig_name, spread, monotonic, spearman))
    
    signal_scores.sort(key=lambda x: x[1], reverse=True)
    
    for sig, spread, mono, spearman in signal_scores[:20]:
        print(f"  {sig:30s}  Spread: {spread:+.4f}  Mono: {mono}  Spearman: {spearman:.3f}")
    
    for fwd in [20, 120]:
        print(f"\n--- {fwd}D FORWARD ---")
        for sig_name, fwd_dict in results.items():
            if fwd in fwd_dict:
                spread = fwd_dict[fwd].get('q10_q1_spread', np.nan)
                if pd.notna(spread) and spread > 0.005:
                    print(f"  {sig_name:30s}  Spread: {spread:+.4f}")
    
    # Save
    with open('research/strategy-lab/strategy_exploration_results.pkl', 'wb') as f:
        pickle.dump(results, f)
    
    print("\nResults saved.")
    
    # Robust candidates
    print("\n" + "=" * 60)
    print("ROBUST CANDIDATE SELECTION")
    print("=" * 60)
    
    robust = []
    for sig_name, fwd_dict in results.items():
        spreads = []
        monotonic_count = 0
        spearman_sum = 0
        spearman_count = 0
        for fwd in [20, 60, 120]:
            if fwd in fwd_dict:
                s = fwd_dict[fwd].get('q10_q1_spread', np.nan)
                m = fwd_dict[fwd].get('monotonic', False)
                sp = fwd_dict[fwd].get('spearman_ic', np.nan)
                if pd.notna(s) and s > 0:
                    spreads.append(s)
                    if m:
                        monotonic_count += 1
                if pd.notna(sp):
                    spearman_sum += sp
                    spearman_count += 1
        
        avg_spearman = spearman_sum / spearman_count if spearman_count > 0 else np.nan
        
        if len(spreads) >= 2 and np.mean(spreads) > 0.005:
            robust.append({
                'signal': sig_name,
                'mean_spread': np.mean(spreads),
                'spreads': spreads,
                'monotonic_count': monotonic_count,
                'n_periods': len(spreads),
                'avg_spearman': avg_spearman
            })
    
    robust.sort(key=lambda x: x['mean_spread'], reverse=True)
    
    for r in robust[:15]:
        print(f"  {r['signal']:30s}  Mean Spread: {r['mean_spread']:.4f}  Periods: {r['n_periods']}  Mono: {r['monotonic_count']}  Avg Spearman: {r['avg_spearman']:.3f}")
    
    return results

if __name__ == '__main__':
    results = main()