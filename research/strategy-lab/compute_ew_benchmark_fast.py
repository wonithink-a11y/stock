#!/usr/bin/env python
"""Compute EW benchmark using vectorized pandas operations."""
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
    
    # Filter to strategy period
    start_date = '2014-05-13'
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
    print(f"Tickers with at least one price: {len(tickers)}")
    
    # Equal weight: each ticker gets 1/N of capital
    n_tickers = len(tickers)
    initial_capital = 100_000_000
    allocation_per_ticker = initial_capital / n_tickers
    
    # Find first available price for each ticker
    first_prices = {}
    for ticker in tickers:
        series = pivot_aligned[ticker]
        first_valid = series.first_valid_index()
        if first_valid is not None:
            first_prices[ticker] = series[first_valid]
    
    valid_tickers = [t for t in tickers if t in first_prices]
    print(f"Valid tickers: {len(valid_tickers)}")
    
    # Compute shares per ticker (fractional for exact equal weight)
    shares = {t: initial_capital / len(valid_tickers) / first_prices[t] for t in valid_tickers}
    
    # Compute daily portfolio value using vectorized operations
    print("Computing daily portfolio value...")
    
    # For each ticker: shares * price_t
    # We only have prices from first_valid_index onwards, before that NaN
    # Multiply each column by its shares
    prices_valid = pivot_aligned[valid_tickers]
    shares_series = pd.Series(shares)
    
    # Portfolio value = sum(shares_t * price_t) for each date
    # Where price is NaN before first valid, treat as 0 (not yet purchased)
    portfolio_values = (prices_valid * shares_series).sum(axis=1, skipna=False)
    
    # Before first valid price for any ticker, portfolio is 0
    # After first ticker appears, we only count tickers that have appeared
    # This is handled by skipna=False - NaN * shares = NaN, sum = NaN
    # But we want: before ANY ticker appears -> 0, after some appear -> sum of appeared
    
    # Better: fill NaN with 0 for tickers not yet appeared
    # But we need to know when each ticker first appears
    first_appearance = {}
    for t in valid_tickers:
        series = pivot_aligned[t]
        first_valid = series.first_valid_index()
        if first_valid is not None:
            first_appearance[t] = first_valid
    
    # Create mask of which tickers are active on each date
    # This is complex - let's use a simpler approach
    # For each date, sum shares * price for tickers that have price on that date
    
    # Actually, the standard EW buy & hold:
    # On day 0, buy equal $ amount of each ticker at its first available price
    # Then hold forever, value = sum(shares * current_price)
    # If price is NaN (ticker not yet listed or delisted), use last known price
    
    # The pivot_aligned is already forward-filled, so NaN only before first appearance
    # For dates before first appearance, we should not count that ticker yet
    # So: value = sum(shares * price) where price is not NaN
    
    portfolio_values = (pivot_aligned[valid_tickers] * pd.Series(shares)).sum(axis=1, skipna=True)
    
    # Before any ticker appears, portfolio value should be initial_capital (all cash)
    # But since we're doing buy & hold, we assume immediate deployment on first date
    # Actually, on the first date where we have prices, we buy all available tickers
    # So portfolio value starts at 0 before first purchase, then initial_capital after
    
    # Find first date where at least one ticker has price
    first_date_with_price = portfolio_values.first_valid_index()
    print(f"First date with price data: {first_date_with_price}")
    
    # Equity curve
    equity_curve = []
    for date_str in all_dates_str:
        val = portfolio_values.get(date_str)
        if pd.notna(val):
            equity_curve.append((date_str, float(val)))
        else:
            # Before first price, equity is initial_capital (all cash)
            equity_curve.append((date_str, float(initial_capital)))
    
    print(f"Equity curve length: {len(equity_curve)}")
    print(f"First: {equity_curve[0]}")
    print(f"Last: {equity_curve[-1]}")
    
    # Compute annual returns
    from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe
    
    def compute_annual(equity_curve):
        if len(equity_curve) < 2:
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
                start_eq = yearly_equity[prev_year][-1][1]
                start_date = yearly_equity[prev_year][-1][0]
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
    
    yearly_equity = {}
    for d, eq in equity_curve:
        year = d[:4]
        if year not in yearly_equity:
            yearly_equity[year] = []
        yearly_equity[year].append((d, eq))
    
    annual = compute_annual(equity_curve)
    
    print("\nAnnual returns:")
    for year, data in annual.items():
        print(f"  {year}: Return={data['annualReturn']:.4%}, MDD={data['maxDrawdown']:.4%}, CAGR={data['cagr']:.4%}")
    
    # Save
    output = {
        "benchmark": "Universe_EW_BuyHold",
        "period": "2014-05-13 to 2026-08-03",
        "initialCapital": 100000000,
        "tickers": len(valid_tickers),
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
    main()