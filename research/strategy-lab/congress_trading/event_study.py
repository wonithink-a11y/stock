#!/usr/bin/env python3
"""
Event Study: Congressional Stock Trading - Publication Date Alpha

Tests whether buying after PTR publication/filing date generates SPY-adjusted alpha.

PIT Rules:
- Signal timing: filing_date (publication date), NOT transaction_date
- Entry: next trading day OPEN after filing_date
- Transaction date is future info - used only for lag analysis

Horizons: +1D, +5D, +20D, +60D, +120D, +252D trading days
Costs: 30bps round-trip base, 10/50bps sensitivity
Groups: All, House, Senate, Dem, GOP, Leadership, High-volume politicians
Split: TRAIN 2012-2020, TEST 2021-present
"""
import warnings
warnings.filterwarnings('ignore')

import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats as sps
from statsmodels.stats.weightstats import DescrStatsW

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = REPO_ROOT / "research" / "strategy-lab" / "congress_trading" / "data"
PARSED_DIR = DATA_DIR / "parsed"
FINDINGS_DIR = REPO_ROOT / "research" / "strategy-lab" / "findings" / "congress-trading"

FINDINGS_DIR.mkdir(parents=True, exist_ok=True)

# Trading calendar (NYSE)
try:
    import pandas_market_calendars as mcal
    NYSE = mcal.get_calendar('NYSE')
except ImportError:
    print("pandas_market_calendars not installed, using approximate calendar")
    NYSE = None

HORIZONS_TD = [1, 5, 20, 60, 120, 252]  # Trading days
COST_BPS_OPTIONS = [10, 30, 50]  # Round-trip


def get_trading_calendar(start: str, end: str) -> pd.DatetimeIndex:
    """Get NYSE trading days."""
    if NYSE is not None:
        schedule = NYSE.schedule(start_date=start, end_date=end)
        return schedule.index
    else:
        # Approximate: business days
        return pd.bdate_range(start=start, end=end)


def load_spy_data(start: str, end: str) -> pd.Series:
    """Load SPY daily returns for benchmarking."""
    spy_file = PARSED_DIR / "spy_daily.parquet"
    
    if spy_file.exists():
        spy = pd.read_parquet(spy_file)
        spy.index = pd.to_datetime(spy.index)
    else:
        # Fetch from Yahoo Finance
        import yfinance as yf
        data = yf.download('SPY', start=start, end=end, progress=False, auto_adjust=True)
        # yfinance returns MultiIndex columns with auto_adjust=True
        if isinstance(data.columns, pd.MultiIndex):
            # Extract SPY's Close column
            if ('Close', 'SPY') in data.columns:
                spy = data[('Close', 'SPY')]
            else:
                # Fallback: get first Close column
                close_cols = [c for c in data.columns if c[0] == 'Close']
                spy = data[close_cols[0]]
        else:
            spy = data['Close'] if 'Close' in data.columns else data['Adj Close']
        spy.to_parquet(spy_file)
    
    # Ensure we have a Series
    if isinstance(spy, pd.DataFrame):
        spy = spy.iloc[:, 0]
    
    # Calculate daily returns
    spy_ret = spy.pct_change().dropna()
    return spy_ret


def add_trading_days(date: pd.Timestamp, n: int, calendar: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    """Add n trading days to date."""
    if date not in calendar:
        # Find next trading day
        idx = calendar.searchsorted(date)
        if idx >= len(calendar):
            return None
        date = calendar[idx]
    idx = calendar.get_loc(date)
    target_idx = idx + n
    if target_idx >= len(calendar):
        return None
    return calendar[target_idx]


def compute_event_returns(
    events: pd.DataFrame,
    spy_ret: pd.Series,
    calendar: pd.DatetimeIndex,
    horizons: List[int],
    cost_bps: float
) -> pd.DataFrame:
    """Compute returns for each event at specified horizons."""
    
    results = []
    cost = cost_bps / 10000  # Convert bps to decimal
    
    for _, row in events.iterrows():
        filing_date = pd.Timestamp(row['filing_date'])
        ticker = row['ticker']
        buy_sell = row['buy_sell']
        
        # Entry: next trading day OPEN after filing_date
        entry_date = add_trading_days(filing_date, 1, calendar)
        if entry_date is None:
            continue
        
        event_result = {
            'politician': row['politician'],
            'chamber': row['chamber'],
            'party': row.get('party'),
            'ticker': ticker,
            'buy_sell': buy_sell,
            'filing_date': filing_date,
            'entry_date': entry_date,
        }
        
        # For each horizon, compute exit date
        for h in horizons:
            exit_date = add_trading_days(entry_date, h, calendar)
            if exit_date is None:
                event_result[f'ret_{h}d'] = np.nan
                event_result[f'spy_{h}d'] = np.nan
                event_result[f'excess_{h}d'] = np.nan
                continue
            
            # We need price data for the ticker
            # This will be filled in later when we have price data
            event_result[f'exit_date_{h}d'] = exit_date
        
        results.append(event_result)
    
    return pd.DataFrame(results)


def attach_price_data(
    events_df: pd.DataFrame,
    horizons: List[int],
    spy_ret: pd.Series
) -> pd.DataFrame:
    """Attach price data for all tickers in events."""
    import yfinance as yf
    
    tickers = events_df['ticker'].unique()
    print(f"Fetching price data for {len(tickers)} tickers...")
    
    # Determine date range needed
    min_date = events_df['entry_date'].min()
    max_date = None
    for h in horizons:
        col = f'exit_date_{h}d'
        if col in events_df.columns:
            col_max = events_df[col].max()
            if not pd.isna(col_max):
                if max_date is None or col_max > max_date:
                    max_date = col_max
    
    if max_date is None:
        return events_df
    
    # Add buffer
    start = (min_date - pd.Timedelta(days=10)).strftime('%Y-%m-%d')
    end = (max_date + pd.Timedelta(days=10)).strftime('%Y-%m-%d')
    
    price_data = {}
    for ticker in tickers:
        try:
            # Clean ticker
            clean_ticker = ticker.replace('.', '-')
            data = yf.download(clean_ticker, start=start, end=end, progress=False, auto_adjust=True)
            if len(data) > 0:
                # yfinance with auto_adjust=True returns MultiIndex columns: (field, ticker)
                if isinstance(data.columns, pd.MultiIndex):
                    # Extract Close for this ticker
                    close_col = ('Close', clean_ticker) if ('Close', clean_ticker) in data.columns else 'Close'
                    price_data[ticker] = data[close_col]
                else:
                    price_data[ticker] = data['Close']
        except Exception as e:
            print(f"  Failed to fetch {ticker}: {e}")
    
    # Fill in returns
    for h in horizons:
        entry_col = 'entry_date'
        exit_col = f'exit_date_{h}d'
        ret_col = f'ret_{h}d'
        spy_col = f'spy_{h}d'
        excess_col = f'excess_{h}d'
        
        events_df[ret_col] = np.nan
        events_df[spy_col] = np.nan
        events_df[excess_col] = np.nan
        
        for idx, row in events_df.iterrows():
            ticker = row['ticker']
            entry = row[entry_col]
            exit_dt = row[exit_col]
            
            if pd.isna(entry) or pd.isna(exit_dt) or ticker not in price_data:
                continue
            
            prices = price_data[ticker]
            # Find closest available dates
            try:
                entry_price = prices.asof(entry)
                exit_price = prices.asof(exit_dt)
                
                if pd.isna(entry_price) or pd.isna(exit_price) or entry_price <= 0:
                    continue
                
                if row['buy_sell'] == 'BUY':
                    gross_ret = exit_price / entry_price - 1
                else:  # SELL - short position
                    gross_ret = entry_price / exit_price - 1
                
                # SPY return for same period
                spy_start = spy_ret.asof(entry)
                spy_end = spy_ret.asof(exit_dt)
                if not pd.isna(spy_start) and not pd.isna(spy_end):
                    # Approximate SPY cumulative return
                    spy_mask = (spy_ret.index >= entry) & (spy_ret.index <= exit_dt)
                    spy_cum = float((1 + spy_ret[spy_mask]).prod() - 1)
                else:
                    spy_cum = np.nan
                
                events_df.at[idx, ret_col] = gross_ret
                events_df.at[idx, spy_col] = spy_cum
                events_df.at[idx, excess_col] = gross_ret - spy_cum if not np.isnan(spy_cum) else np.nan
                
            except Exception as e:
                print(f"    Error computing returns for idx={idx}, ticker={ticker}: {e}")
                continue
    
    return events_df


def compute_nw_tstat(returns: pd.Series, max_lag: int = 5) -> Tuple[float, float]:
    """Newey-West adjusted t-statistic."""
    clean = returns.dropna()
    if len(clean) < 10:
        return np.nan, np.nan
    
    mean_ret = clean.mean()
    n = len(clean)
    
    # Newey-West variance
    var = clean.var(ddof=1)
    for lag in range(1, min(max_lag + 1, n)):
        weight = 1 - lag / (max_lag + 1)
        autocov = clean.autocorr(lag)
        if not np.isnan(autocov):
            var += 2 * weight * autocov * clean.var(ddof=1)
    
    se = np.sqrt(var / n)
    t_stat = mean_ret / se if se > 0 else np.nan
    
    # p-value (two-sided)
    from scipy import stats
    p_val = 2 * stats.t.sf(abs(t_stat), df=n-1) if not np.isnan(t_stat) else np.nan
    
    return t_stat, p_val


def analyze_group(
    group_name: str,
    events: pd.DataFrame,
    horizons: List[int],
    cost_bps: float
) -> Dict:
    """Analyze a group of events."""
    cost = cost_bps / 10000
    
    result = {
        'group': group_name,
        'n_events': len(events),
        'unique_politicians': events['politician'].nunique() if 'politician' in events else 0,
        'unique_tickers': events['ticker'].nunique() if 'ticker' in events else 0,
        'horizons': {}
    }
    
    for h in horizons:
        excess_col = f'excess_{h}d'
        ret_col = f'ret_{h}d'
        spy_col = f'spy_{h}d'
        
        if excess_col not in events.columns:
            continue
        
        excess = events[excess_col].dropna() - cost
        gross = events[ret_col].dropna()
        spy = events[spy_col].dropna()
        
        if len(excess) < 5:
            result['horizons'][f'{h}d'] = {'n': len(excess), 'insufficient': True}
            continue
        
        t_stat, p_val = compute_nw_tstat(excess)
        
        result['horizons'][f'{h}d'] = {
            'n': len(excess),
            'mean_excess_pct': round(excess.mean() * 100, 4),
            'median_excess_pct': round(excess.median() * 100, 4),
            'std_excess_pct': round(excess.std() * 100, 4),
            'mean_gross_pct': round(gross.mean() * 100, 4),
            'mean_spy_pct': round(spy.mean() * 100, 4) if len(spy) > 0 else np.nan,
            'win_rate_pct': round((excess > 0).mean() * 100, 2),
            't_stat_nw': round(t_stat, 3) if not np.isnan(t_stat) else None,
            'p_value': round(p_val, 4) if not np.isnan(p_val) else None,
            'significant_5pct': p_val < 0.05 if not np.isnan(p_val) else False,
            'profitable': excess.mean() > 0,
        }
    
    return result


def deduplicate_events(events: pd.DataFrame, method: str = 'equal_weight') -> pd.DataFrame:
    """
    Deduplicate events to prevent same ticker/politician from dominating.
    
    Methods:
    - 'equal_weight': Average multiple events for same (politician, ticker, filing_date)
    - 'first_only': Keep only first event per (politician, ticker)
    - 'portfolio': Simulate portfolio with equal weight per unique ticker per day
    """
    if method == 'equal_weight':
        # Average returns for same politician+ticker+filing_date
        cols = ['politician', 'ticker', 'filing_date']
        excess_cols = [c for c in events.columns if c.startswith('excess_')]
        ret_cols = [c for c in events.columns if c.startswith('ret_')]
        spy_cols = [c for c in events.columns if c.startswith('spy_')]
        exit_cols = [c for c in events.columns if c.startswith('exit_date_')]
        other_cols = [c for c in events.columns if c not in cols and c not in excess_cols and c not in ret_cols and c not in spy_cols and c not in exit_cols]
        
        # Group by politician+ticker+filing_date, average all return columns
        all_return_cols = excess_cols + ret_cols + spy_cols
        grouped = events.groupby(cols)[all_return_cols].mean().reset_index()
        
        # Keep other info from first row
        first_info = events.groupby(cols)[other_cols].first().reset_index()
        
        deduped = first_info.merge(grouped, on=cols)
        return deduped
    
    elif method == 'first_only':
        return events.drop_duplicates(subset=['politician', 'ticker'], keep='first')
    
    return events


def portfolio_level_analysis(events: pd.DataFrame, horizons: List[int], cost_bps: float) -> Dict:
    """Simulate equal-weight portfolio of all signals each day."""
    cost = cost_bps / 10000
    
    # Get all unique trading days with signals
    events['filing_date'] = pd.to_datetime(events['filing_date'])
    events['entry_date'] = pd.to_datetime(events['entry_date'])
    
    daily_returns = {}
    daily_spy = {}
    
    for h in horizons:
        excess_col = f'excess_{h}d'
        if excess_col not in events.columns:
            continue
        
        # For each entry date, compute equal-weight portfolio return
        port_excess = events.groupby('entry_date')[excess_col].mean() - cost
        port_gross = events.groupby('entry_date')[f'ret_{h}d'].mean()
        port_spy = events.groupby('entry_date')[f'spy_{h}d'].mean()
        
        daily_returns[h] = port_excess
        daily_spy[h] = port_spy
    
    result = {}
    for h in horizons:
        if h not in daily_returns:
            continue
        excess = daily_returns[h].dropna()
        if len(excess) < 10:
            continue
        
        t_stat, p_val = compute_nw_tstat(excess)
        result[f'{h}d'] = {
            'n_days': len(excess),
            'mean_excess_pct': round(excess.mean() * 100, 4),
            't_stat_nw': round(t_stat, 3) if not np.isnan(t_stat) else None,
            'p_value': round(p_val, 4) if not np.isnan(p_val) else None,
            'win_rate_pct': round((excess > 0).mean() * 100, 2),
        }
    
    return {'portfolio': result}


def publication_lag_analysis(original_events: pd.DataFrame, analyzed_events: pd.DataFrame, horizons: List[int], cost_bps: float) -> Dict:
    """Analyze excess returns by publication lag buckets using original events for lag calculation."""
    cost = cost_bps / 10000
    
    # Use original events for lag calculation
    events = original_events.copy()
    events['transaction_date'] = pd.to_datetime(events['transaction_date'], errors='coerce')
    events['filing_date'] = pd.to_datetime(events['filing_date'], errors='coerce')
    events['lag_days'] = (events['filing_date'] - events['transaction_date']).dt.days
    
    # Map lag_days to analyzed_events by matching on key columns
    # We need to merge lag info into analyzed_events
    key_cols = ['politician', 'ticker', 'filing_date']
    lag_info = events[key_cols + ['lag_days']].drop_duplicates()
    
    # Merge with analyzed_events
    merged = analyzed_events.merge(lag_info, on=key_cols, how='left')
    
    buckets = {
        '0-7': (0, 7),
        '8-15': (8, 15),
        '16-30': (16, 30),
        '31-45': (31, 45),
        '46+': (46, 999),
    }
    
    result = {}
    for bucket_name, (low, high) in buckets.items():
        mask = (merged['lag_days'] >= low) & (merged['lag_days'] <= high)
        bucket_events = merged[mask]
        if len(bucket_events) < 5:
            result[bucket_name] = {'n': len(bucket_events), 'insufficient': True}
            continue
        
        bucket_result = analyze_group(f'lag_{bucket_name}', bucket_events, horizons, cost_bps)
        result[bucket_name] = bucket_result
    
    return result


def main():
    print("=" * 70)
    print("Congressional Trading Event Study - Publication Date Alpha")
    print("=" * 70)
    
    # Load data
    combined_file = PARSED_DIR / "congress_ptr_combined.parquet"
    if not combined_file.exists():
        print("Data not found. Run fetch_official_ptr.py first.")
        return 1
    
    df = pd.read_parquet(combined_file)
    print(f"Loaded {len(df)} transactions")
    
    # Filter: only BUY, valid dates, has ticker
    df = df[
        (df['buy_sell'] == 'BUY') & 
        (df['ticker'].notna()) & 
        (df['ticker'] != '') &
        (df['filing_date'].notna()) &
        (df['transaction_date'].notna())
    ].copy()
    print(f"After BUY filter: {len(df)} events")
    
    # Parse dates
    df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
    df['filing_date'] = pd.to_datetime(df['filing_date'], errors='coerce')
    df = df.dropna(subset=['transaction_date', 'filing_date'])
    print(f"After date parse: {len(df)} events")
    
    # PIT check: filing_date must be >= transaction_date
    pit_violation = df[df['filing_date'] < df['transaction_date']]
    if len(pit_violation) > 0:
        print(f"WARNING: {len(pit_violation)} PIT violations (filing < transaction)")
        df = df[df['filing_date'] >= df['transaction_date']]
    
    # Add lag
    df['lag_days'] = (df['filing_date'] - df['transaction_date']).dt.days
    
    # Date range
    print(f"Date range: {df['filing_date'].min()} to {df['filing_date'].max()}")
    
    # Split: TRAIN 2012-2020, TEST 2021+
    train_end = '2020-12-31'
    test_start = '2021-01-01'
    
    train_df = df[df['filing_date'] <= train_end].copy()
    test_df = df[df['filing_date'] >= test_start].copy()
    
    print(f"TRAIN (2012-2020): {len(train_df)} events")
    print(f"TEST (2021+): {len(test_df)} events")
    
    if len(test_df) < 10:
        print("TEST sample too small, using 80/20 split")
        # Time-based 80/20
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()
        print(f"Adjusted TRAIN: {len(train_df)}, TEST: {len(test_df)}")
    
    # Setup calendar and SPY
    start_date = df['filing_date'].min().strftime('%Y-%m-%d')
    end_date = df['filing_date'].max().strftime('%Y-%m-%d')
    
    calendar = get_trading_calendar(start_date, end_date)
    spy_ret = load_spy_data(start_date, end_date)
    
    # Process TRAIN
    print("\nProcessing TRAIN period...")
    train_events = compute_event_returns(train_df, spy_ret, calendar, HORIZONS_TD, 30)
    train_events = attach_price_data(train_events, HORIZONS_TD, spy_ret)
    
    # Process TEST
    print("Processing TEST period...")
    test_events = compute_event_returns(test_df, spy_ret, calendar, HORIZONS_TD, 30)
    test_events = attach_price_data(test_events, HORIZONS_TD, spy_ret)
    
    # Save raw events
    train_events.to_parquet(FINDINGS_DIR / "train_events.parquet")
    test_events.to_parquet(FINDINGS_DIR / "test_events.parquet")
    
    # Analysis - keep original dfs for lag analysis
    original_events_map = {
        'TRAIN': train_df,
        'TEST': test_df,
        'FULL': pd.concat([train_df, test_df]),
    }
    analyzed_events_map = {
        'TRAIN': train_events,
        'TEST': test_events,
        'FULL': pd.concat([train_events, test_events]),
    }
    
    all_results = {}
    
    for period_name in ['TRAIN', 'TEST', 'FULL']:
        events = analyzed_events_map[period_name]
        original_events = original_events_map[period_name]
        
        print(f"\n{'='*50}")
        print(f"Analysis: {period_name} ({len(events)} events)")
        print(f"{'='*50}")
        
        period_results = {}
        
        for cost_bps in COST_BPS_OPTIONS:
            cost_results = {}
            
            # Define groups
            groups = {
                'All': events,
                'House': events[events['chamber'] == 'House'],
                'Senate': events[events['chamber'] == 'Senate'],
            }
            
            # Add party groups if party data exists
            if 'party' in events.columns:
                groups['Democrat'] = events[events['party'] == 'Democrat']
                groups['Republican'] = events[events['party'] == 'Republican']
            
            # Leadership group (placeholder - would need leadership list)
            # For now, use top 10 by trade count
            if len(events) > 0:
                top_politicians = events['politician'].value_counts().head(10).index
                groups['Top10_Politicians'] = events[events['politician'].isin(top_politicians)]
            
            for group_name, group_events in groups.items():
                if len(group_events) < 5:
                    continue
                
                print(f"  {group_name}: {len(group_events)} events")
                group_result = analyze_group(group_name, group_events, HORIZONS_TD, cost_bps)
                cost_results[group_name] = group_result
            
            # Deduplicated analysis
            print("  Deduplicated (equal weight)...")
            deduped = deduplicate_events(events, 'equal_weight')
            cost_results['Deduplicated_EqualWeight'] = analyze_group('Deduplicated_EqualWeight', deduped, HORIZONS_TD, cost_bps)
            
            # Portfolio-level
            print("  Portfolio-level...")
            cost_results['Portfolio_Level'] = portfolio_level_analysis(events, HORIZONS_TD, cost_bps)
            
            all_results[f'{period_name}_cost{cost_bps}bps'] = cost_results
        
        # Publication lag analysis (only for base 30bps)
        print("  Publication lag analysis...")
        # Use original events for lag calculation
        all_results[f'{period_name}_lag_analysis'] = publication_lag_analysis(original_events, events, HORIZONS_TD, 30)
    
    # Save all results
    output_file = FINDINGS_DIR / "event_study_results.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {output_file}")
    
    # Generate markdown report
    generate_report(all_results, FINDINGS_DIR / "event_study_report.md")
    print(f"Report saved to {FINDINGS_DIR / 'event_study_report.md'}")
    
    return 0


def generate_report(results: Dict, output_path: Path):
    """Generate markdown report from results."""
    lines = []
    lines.append("# Congressional Trading Event Study Report\n")
    lines.append(f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n")
    lines.append("---\n\n")
    
    for period_key, period_data in results.items():
        if 'lag_analysis' in period_key:
            continue
        
        lines.append(f"## {period_key}\n\n")
        
        for cost_key, cost_data in period_data.items():
            if isinstance(cost_data, dict) and 'group' not in cost_data:
                lines.append(f"### Cost: {cost_key}\n\n")
                
                for group_name, group_result in cost_data.items():
                    if group_name in ['Portfolio_Level']:
                        continue
                    if not isinstance(group_result, dict) or 'horizons' not in group_result:
                        continue
                    
                    lines.append(f"#### {group_name} (n={group_result['n_events']})\n\n")
                    lines.append("| Horizon | N | Excess Mean | Excess Median | Win% | t-stat (NW) | p-value | Sig |\n")
                    lines.append("|---------|---|-------------|---------------|------|-------------|---------|-----|\n")
                    
                    for horizon, h_data in group_result['horizons'].items():
                        if h_data.get('insufficient'):
                            lines.append(f"| {horizon} | {h_data['n']} | - | - | - | - | - | - |\n")
                        else:
                            sig = "✓" if h_data.get('significant_5pct') else ""
                            lines.append(f"| {horizon} | {h_data['n']} | {h_data['mean_excess_pct']:.4f}% | {h_data['median_excess_pct']:.4f}% | {h_data['win_rate_pct']:.1f}% | {h_data.get('t_stat_nw', 'N/A')} | {h_data.get('p_value', 'N/A')} | {sig} |\n")
                    lines.append("\n")
        
        # Lag analysis
        lag_key = f'{period_key.split("_")[0]}_lag_analysis' if '_' in period_key else f'{period_key}_lag_analysis'
        if lag_key in results:
            lines.append("### Publication Lag Analysis\n\n")
            lag_data = results[lag_key]
            for bucket, bucket_result in lag_data.items():
                if bucket_result.get('insufficient'):
                    continue
                lines.append(f"#### Lag {bucket} days\n\n")
                lines.append("| Horizon | N | Excess Mean | Win% | t-stat |\n")
                lines.append("|---------|---|-------------|------|--------|\n")
                for horizon, h_data in bucket_result['horizons'].items():
                    if not h_data.get('insufficient'):
                        lines.append(f"| {horizon} | {h_data['n']} | {h_data['mean_excess_pct']:.4f}% | {h_data['win_rate_pct']:.1f}% | {h_data.get('t_stat_nw', 'N/A')} |\n")
                lines.append("\n")
    
    output_path.write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())