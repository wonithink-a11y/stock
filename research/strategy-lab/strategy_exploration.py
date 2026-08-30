"""
Independent Korean Market Strategy Exploration
Uses actual A2a price data (2016-2026) + A1a universe
No foreign investor data (A4 not available)
"""
import sys
sys.path.insert(0, 'research/strategy-lab')

import gzip
import json
import pickle
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

# ============================================================
# 1. DATA LOADING
# ============================================================

def load_universe():
    """Load A1A universe (currently listed KOSPI/KOSDAQ)"""
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

def load_price_data(tickers, start_date='2016-01-01', end_date='2026-08-03'):
    """Load A2a price data for given tickers and date range"""
    bars = defaultdict(list)
    
    for year in range(2016, 2027):
        path = f'data/backfill/price/a2a/{year}.jsonl.gz'
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            for line in f:
                row = json.loads(line)
                if row['ticker'] in tickers and start_date <= row['date'] <= end_date:
                    bars[row['ticker']].append(row)
    
    # Convert to DataFrames
    dfs = {}
    for ticker, rows in bars.items():
        if len(rows) < 250:  # Need at least 1 year for signals
            continue
        df = pd.DataFrame(rows)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').set_index('date')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        dfs[ticker] = df
    
    return dfs

# ============================================================
# 2. SIGNAL COMPUTATION
# ============================================================

def compute_signals(df):
    """Compute all candidate signals on a ticker's price DataFrame"""
    signals = pd.DataFrame(index=df.index)
    
    # Price series
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
    
    # Momentum (Jegadeesh & Titman style)
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
    
    # Pullback (RSI-based)
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / (loss + 1e-8)
    signals['rsi_14'] = 100 - (100 / (1 + rs))
    
    # Pullback from recent high
    signals['dist_from_high_20'] = (signals['donchian_20_high'] - close) / close
    signals['dist_from_high_60'] = (signals['donchian_60_high'] - close) / close
    
    # Volume signals
    signals['volume_ma_20'] = volume.rolling(20).mean()
    signals['volume_ratio'] = volume / signals['volume_ma_20']
    signals['volume_trend'] = signals['volume_ma_20'].pct_change(20)
    
    # Volatility
    signals['vol_20d'] = signals['ret_1d'].rolling(20).std() * np.sqrt(252)
    signals['vol_60d'] = signals['ret_1d'].rolling(60).std() * np.sqrt(252)
    
    # Moving averages
    signals['ma_5'] = close.rolling(5).mean()
    signals['ma_20'] = close.rolling(20).mean()
    signals['ma_60'] = close.rolling(60).mean()
    signals['ma_120'] = close.rolling(120).mean()
    
    # MA relative position
    signals['ma_5_20'] = close / signals['ma_5'] - 1
    signals['ma_20_60'] = signals['ma_20'] / signals['ma_60'] - 1
    signals['ma_60_120'] = signals['ma_60'] / signals['ma_120'] - 1
    
    # MACD-like
    signals['ema_12'] = close.ewm(span=12).mean()
    signals['ema_26'] = close.ewm(span=26).mean()
    signals['macd'] = signals['ema_12'] - signals['ema_26']
    signals['macd_signal'] = signals['macd'].ewm(span=9).mean()
    signals['macd_hist'] = signals['macd'] - signals['macd_signal']
    
    return signals

# ============================================================
# 3. PORTFOLIO BACKTEST
# ============================================================

def run_decile_backtest(all_signals, price_data_dict, calendar, forward_days_list=[20, 60, 120]):
    """
    Monthly rebalancing decile backtest
    Returns results for each signal and forward period
    """
    cal_dates = pd.to_datetime(calendar)
    
    # Get month-end dates from calendar
    month_ends = []
    for i in range(1, len(cal_dates)):
        if cal_dates[i].month != cal_dates[i-1].month:
            month_ends.append(cal_dates[i-1])
    if cal_dates[-1] not in month_ends:
        month_ends.append(cal_dates[-1])
    
    results = {}
    
    # Get all unique signal names (excluding price/volume columns)
    signal_names = set()
    for ticker, sig_df in all_signals.items():
        signal_names.update(sig_df.columns)
    
    # Filter to actual signal columns
    exclude = {'open', 'high', 'low', 'close', 'volume', 'ret_1d'}
    signal_names = [s for s in signal_names if s not in exclude]
    
    print(f"Testing {len(signal_names)} signals across {len(month_ends)} rebalance dates...")
    
    for signal_name in signal_names:
        results[signal_name] = {}
        
        for fwd in forward_days_list:
            # Collect decile returns for each rebalance date
            decile_returns = {d: [] for d in range(10)}
            
            for reb_date in month_ends:
                if reb_date not in cal_dates:
                    continue
                
                # Get signal values at rebalance date
                ticker_signals = []
                for ticker, sig_df in all_signals.items():
                    if signal_name in sig_df.columns and reb_date in sig_df.index:
                        val = sig_df.loc[reb_date, signal_name]
                        if pd.notna(val):
                            ticker_signals.append((ticker, val))
                
                if len(ticker_signals) < 100:  # Need enough stocks
                    continue
                
                # Sort and assign deciles
                ticker_signals.sort(key=lambda x: x[1])
                n = len(ticker_signals)
                decile_size = n // 10
                
                # Calculate forward returns
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
                                fwd_ret = (exit_px - entry_px) / entry_px
                                fwd_rets.append(fwd_ret)
                    
                    if fwd_rets:
                        decile_returns[d].append(np.mean(fwd_rets))
            
            # Aggregate results
            if any(len(v) > 0 for v in decile_returns.values()):
                avg_returns = [np.mean(decile_returns[d]) if decile_returns[d] else np.nan for d in range(10)]
                q1 = avg_returns[0]
                q10 = avg_returns[9]
                spread = q10 - q1 if pd.notna(q1) and pd.notna(q10) else np.nan
                
                # Check monotonicity
                valid_returns = [(i, avg_returns[i]) for i in range(10) if pd.notna(avg_returns[i])]
                monotonic = True
                if len(valid_returns) >= 2:
                    for i in range(len(valid_returns) - 1):
                        if valid_returns[i][1] > valid_returns[i+1][1]:
                            monotonic = False
                            break
                
                # Spearman correlation
                spearman = np.nan
                if len(valid_returns) == 10:
                    ranks = [v[0] for v in valid_returns]
                    returns = [v[1] for v in valid_returns]
                    spearman = np.corrcoef(ranks, returns)[0,1]
                
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
    
    # Load universe
    universe = load_universe()
    print(f"Universe: {len(universe)} tickers (KOSPI/KOSDAQ)")
    
    # Load calendar
    calendar = load_calendar()
    print(f"Calendar: {len(calendar)} trading days")
    
    # Load price data
    print("\nLoading price data...")
    price_data = load_price_data(universe)
    print(f"Loaded {len(price_data)} tickers with sufficient history")
    
    # Compute signals
    print("\nComputing signals...")
    all_signals = {}
    for ticker, df in price_data.items():
        sig = compute_signals(df)
        all_signals[ticker] = sig
    
    print(f"Computed signals for {len(all_signals)} tickers")
    
    # Run decile backtest
    print("\nRunning decile backtest...")
    results = run_decile_backtest(all_signals, price_data, calendar)
    
    # Print top signals by Q10-Q1 spread
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
    
    # Also check 20D and 120D
    for fwd in [20, 120]:
        print(f"\n--- {fwd}D FORWARD ---")
        for sig_name, fwd_dict in results.items():
            if fwd in fwd_dict:
                spread = fwd_dict[fwd].get('q10_q1_spread', np.nan)
                if pd.notna(spread) and spread > 0.005:  # Only positive spreads
                    print(f"  {sig_name:30s}  Spread: {spread:+.4f}")
    
    # Save results
    with open('research/strategy-lab/strategy_exploration_results.pkl', 'wb') as f:
        pickle.dump(results, f)
    
    print("\nResults saved to research/strategy-lab/strategy_exploration_results.pkl")
    
    # Identify robust candidates
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