#!/usr/bin/env python
"""Compute EW benchmark correctly using vectorized pandas operations.
Start from first date with good coverage (2014-05-15)."""
import sys
import os
import json
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke
from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe


def compute_annual_returns(equity_curve):
    """Compute annual breakdown from equity curve."""
    if not equity_curve or len(equity_curve) < 2:
        return {}
    
    yearly_equity = {}
    for d, eq in equity_curve:
        year = d[:4]
        if year not in yearly_equity:
            yearly_equity[year] = []
        yearly_equity[year].append((d, eq))
    
    annual = {}
    sorted_years = sorted(yearly_equity.keys())
    
    for i, year in enumerate(sorted_years):
        year_eq = yearly_equity[year]
        
        if i == 0:
            start_eq = equity_curve[0][1]
            start_date = equity_curve[0][0]
        else:
            prev_year = sorted_years[i-1]
            prev_eq = yearly_equity[prev_year]
            start_eq = prev_eq[-1][1]
            start_date = prev_eq[-1][0]
        
        end_eq = year_eq[-1][1]
        end_date = year_eq[-1][0]
        
        year_equity_curve = [(start_date, start_eq)] + year_eq
        
        ann_return = total_return(year_equity_curve)
        ann_cagr = cagr(year_equity_curve)
        ann_mdd = max_drawdown(year_equity_curve)
        ann_sharpe = sharpe(year_equity_curve)
        
        annual[year] = {
            "startDate": start_date,
            "startEquity": start_eq,
            "endDate": end_date,
            "endEquity": end_eq,
            "annualReturn": ann_return,
            "maxDrawdown": ann_mdd,
            "cagr": ann_cagr,
            "sharpe": ann_sharpe,
        }
    
    return annual


def main():
    print("Loading parquet cache...")
    df = pd.read_parquet('.cache/a2a/a0f2acb7cc9639ff00c07f26.parquet')
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    
    print(f"Data shape: {df.shape}")
    print(f"Tickers: {df['ticker'].nunique()}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")
    
    # Use first date with good coverage (2014-05-15 has 1497 tickers)
    # This is also before strategy's first signal (2014-06-16)
    start_date = '2014-05-15'
    end_date = '2026-08-03'
    mask = (df['date'] >= pd.Timestamp(start_date)) & (df['date'] <= pd.Timestamp(end_date))
    df_filtered = df[mask].copy()
    
    # Get calendar from runner
    print("Getting calendar...")
    result = run_smoke('trend_breakout_v1', start_date, end_date, 
                       'C:/Users/User/projects/stock', ticker_subset=['005930'])
    calendar = result['calendar']
    all_dates = calendar.sessions_between(start_date, end_date)
    all_dates_str = [d if isinstance(d, str) else d.strftime('%Y-%m-%d') for d in all_dates]
    
    # Pivot to wide format: date x ticker -> close
    print("Pivoting to wide format...")
    df_filtered['date_str'] = df_filtered['date'].dt.strftime('%Y-%m-%d')
    pivot = df_filtered.pivot_table(index='date_str', columns='ticker', values='close', aggfunc='first')
    
    # Reindex to all trading dates (forward fill for carry-forward)
    print("Reindexing and forward filling...")
    pivot_aligned = pivot.reindex(all_dates_str).ffill()
    
    # Get tickers that have at least one price
    tickers = pivot_aligned.columns.dropna()
    print(f"Total tickers with data from {start_date}: {len(tickers)}")
    
    # Equal weight: each ticker gets 1/N of capital
    n_tickers = len(tickers)
    initial_capital = 100_000_000
    allocation_per_ticker = initial_capital / n_tickers
    
    # Find first available price for each ticker
    first_prices = {}
    first_dates = {}
    for ticker in tickers:
        series = pivot_aligned[ticker]
        first_valid = series.first_valid_index()
        if first_valid is not None:
            first_prices[ticker] = series[first_valid]
            first_dates[ticker] = first_valid
    
    valid_tickers = [t for t in tickers if t in first_prices]
    print(f"Valid tickers with price in range: {len(valid_tickers)}")
    
    if not valid_tickers:
        print("No valid tickers!")
        return
    
    # Shares per ticker (fractional for exact equal weight)
    shares = {t: initial_capital / n_tickers / first_prices[t] for t in valid_tickers}
    
    # Compute daily portfolio value correctly:
    # On each date, portfolio = sum(shares_t * price_t) for tickers that have appeared
    # + cash for tickers not yet appeared
    
    # Cash deployed so far = sum(shares_t * first_price_t) for appeared tickers
    # Remaining cash = initial_capital - cash_deployed
    
    # We need to track which tickers have appeared by each date
    # A ticker "appears" on its first_valid_index date
    
    print("Computing daily portfolio value...")
    
    # Create a DataFrame: date x ticker -> 1 if appeared, 0 otherwise
    appeared = pd.DataFrame(index=all_dates_str, columns=valid_tickers, dtype=bool)
    
    for ticker in valid_tickers:
        first_date = first_dates[ticker]
        idx = all_dates_str.index(first_date)
        appeared.loc[all_dates_str[idx:], ticker] = True
    
    appeared = appeared.fillna(False)
    
    # Compute deployed cash per date: sum(shares_t * first_price_t) for appeared tickers
    shares_series = pd.Series(shares)
    first_prices_series = pd.Series(first_prices)
    deployed_per_ticker = shares_series * first_prices_series  # capital per ticker = initial_capital / n_tickers
    
    # Deployed cash on each date
    deployed_cash = (appeared.astype(float) * deployed_per_ticker).sum(axis=1)
    remaining_cash = initial_capital - deployed_cash
    
    # Market value of positions on each date
    # price * shares for appeared tickers
    prices_valid = pivot_aligned[valid_tickers]
    position_value = (prices_valid * shares_series).sum(axis=1, skipna=True)
    
    # Total portfolio value = position_value + remaining_cash
    portfolio_values = position_value + remaining_cash
    
    # Equity curve
    equity_curve = []
    for date_str in all_dates_str:
        val = portfolio_values.get(date_str)
        if pd.notna(val):
            equity_curve.append((date_str, float(val)))
        else:
            equity_curve.append((date_str, float(initial_capital)))
    
    print(f"Equity curve length: {len(equity_curve)}")
    print(f"First: {equity_curve[0]}")
    print(f"Last: {equity_curve[-1]}")
    
    # Compute annual returns
    annual = compute_annual_returns(equity_curve)
    
    print("\nAnnual returns:")
    for year, data in annual.items():
        print(f"  {year}: Return={data['annualReturn']:.4%}, MDD={data['maxDrawdown']:.4%}, CAGR={data['cagr']:.4%}")
    
    # Save
    output = {
        "benchmark": "Universe_EW_BuyHold",
        "period": f"{start_date} to {end_date}",
        "initialCapital": initial_capital,
        "tickers": n_tickers,
        "note": "Starts 2014-05-15 (first date with ~1500 tickers). Excludes 1 ticker on 2014-05-13/14.",
        "annual": annual,
    }
    
    output_dir = "reports/2026-08-15-trend-breakout-v1-benchmark-analysis"
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, "universe_ew_benchmark.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    import os
    import pickle
    main()