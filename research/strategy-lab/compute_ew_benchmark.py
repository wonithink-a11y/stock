#!/usr/bin/env python
"""Compute EW benchmark using parquet cache directly for speed."""
import sys
import os
import json
import pandas as pd
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe
from engine.runner import run_smoke


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


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
        
        from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe
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


def build_ew_equity_curve_from_parquet(parquet_path, calendar, start_date, end_date, initial_capital=100_000_000):
    """Build equal-weight buy & hold equity curve from parquet cache."""
    # Load parquet
    df = pd.read_parquet(parquet_path)
    df['date_str'] = df['date'].dt.strftime('%Y-%m-%d')
    
    # Get all trading dates from calendar
    all_dates = calendar.sessions_between(start_date, end_date)
    
    # Get unique tickers
    tickers = df['ticker'].unique()
    print(f"Total tickers in parquet: {len(tickers)}")
    
    # Find first available price for each ticker within date range
    ticker_first_price = {}
    ticker_first_date = {}
    
    # Filter df to date range
    mask = (df['date'] >= pd.Timestamp(start_date)) & (df['date'] <= pd.Timestamp(end_date))
    df_filtered = df[mask]
    
    for ticker in tickers:
        ticker_df = df_filtered[df_filtered['ticker'] == ticker]
        if len(ticker_df) > 0:
            first_row = ticker_df.iloc[0]
            ticker_first_price[ticker] = first_row['close']
            ticker_first_date[ticker] = first_row['date_str']
    
    valid_tickers = [t for t in tickers if t in ticker_first_price]
    print(f"Valid tickers with price in range: {len(valid_tickers)}")
    
    if not valid_tickers:
        return []
    
    n_valid = len(valid_tickers)
    allocation_per_ticker = initial_capital / n_valid
    
    shares_per_ticker = {}
    for t in valid_tickers:
        price = ticker_first_price[t]
        shares_per_ticker[t] = allocation_per_ticker / price  # fractional shares
    
    # Build daily closes dict for fast lookup
    # Create pivot table: date -> ticker -> close
    print("Building daily closes lookup...")
    df_pivot = df_filtered.pivot_table(index='date_str', columns='ticker', values='close', aggfunc='first')
    daily_closes = df_pivot.to_dict('index')
    print(f"Daily closes dict built: {len(daily_closes)} dates")
    
    # Get all trading dates
    all_dates = calendar.sessions_between(start_date, end_date)
    
    # Track equity daily
    equity_curve = []
    
    # Pre-compute ticker list for iteration
    valid_ticker_list = list(shares_per_ticker.keys())
    
    for i, date in enumerate(all_dates):
        closes_today = daily_closes.get(date, {})
        market_value = 0.0
        
        # Vectorized computation would be faster but let's keep it simple
        for t in valid_ticker_list:
            shares = shares_per_ticker[t]
            if t in closes_today:
                market_value += closes_today[t] * shares
            else:
                # Carry forward - find last available close
                # This is the slow part - optimize by pre-computing forward-filled prices
                for prev_date in reversed(all_dates[:all_dates.index(date)]):
                    prev_closes = daily_closes.get(prev_date, {})
                    if t in prev_closes:
                        market_value += prev_closes[t] * shares_per_ticker[t]
                        break
        
        equity_curve.append((date, market_value))
        
        if i % 500 == 0:
            print(f"  Progress: {i}/{len(all_dates)} dates")
    
    return equity_curve


def compute_annual_returns_fast(equity_curve):
    """Compute annual breakdown from equity curve - fast version."""
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
        
        from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe
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
    print("Computing EW benchmark from parquet cache...")
    
    # Load calendar
    from engine.data.calendar import TradingCalendar
    calendar = TradingCalendar(repo_root='C:/Users/User/projects/stock')
    
    parquet_path = '.cache/a2a/a0f2acb7cc9639ff00c07f26.parquet'
    
    # We need a calendar for the date range
    # Let's get it from the runner
    result = run_smoke('trend_breakout_v1', '2014-05-13', '2026-08-03', 
                       'C:/Users/User/projects/stock', ticker_subset=['005930'])
    calendar = result['calendar']
    
    print("Building EW equity curve...")
    equity_curve = build_ew_equity_curve_from_parquet(
        parquet_path, calendar, '2014-05-13', '2026-08-03'
    )
    
    print(f"Equity curve points: {len(equity_curve)}")
    if equity_curve:
        print(f"First: {equity_curve[0]}")
        print(f"Last: {equity_curve[-1]}")
    
    # Compute annual returns
    annual = compute_annual_returns_fast(equity_curve)
    
    print("\nAnnual returns:")
    for year, data in annual.items():
        print(f"  {year}: Return={data['annualReturn']:.4%}, MDD={data['maxDrawdown']:.4%}, CAGR={data['cagr']:.4%}")
    
    # Save
    output = {
        "benchmark": "Universe_EW_BuyHold",
        "period": "2014-05-13 to 2026-08-03",
        "initialCapital": 100000000,
        "tickers": 2558,
        "annual": annual,
    }
    
    output_dir = "reports/2026-08-15-trend-breakout-v1-benchmark-analysis"
    os.makedirs(output_dir, exist_ok=True)
    
    output_path = os.path.join(output_dir, "universe_ew_benchmark.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    import pickle
    import os
    main()