#!/usr/bin/env python
"""Compute benchmark returns (KOSPI, KOSPI200, KOSDAQ, KOSDAQ150, Strategy Universe EW) 
and compare with TREND-BREAKOUT-v1 strategy annual returns."""
import sys
import os
import json
import pickle
import gzip
from datetime import date as _date
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe
import pandas as pd


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def compute_annual_returns(equity_curve):
    """Compute annual breakdown from equity curve."""
    if not equity_curve or len(equity_curve) < 2:
        return {}
    
    yearly_equity = defaultdict(list)
    for d, eq in equity_curve:
        year = d[:4]
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


def build_ew_equity_curve(bars_by_ticker, calendar, start_date, end_date, initial_capital=100_000_000):
    """Build equal-weight buy & hold equity curve from price data.
    
    Proper implementation: allocate equal capital to each ticker on the first date
    where that ticker has a price. This mimics a real investor who buys each stock
    when it first becomes available in the universe.
    """
    all_dates = calendar.sessions_between(start_date, end_date)
    
    # Get all tickers with data
    tickers = list(bars_by_ticker.keys())
    if not tickers:
        return []
    
    # Build daily closes: {date: {ticker: close}}
    daily_closes = defaultdict(dict)
    for ticker, bars in bars_by_ticker.items():
        for idx, row in bars.iterrows():
            d = idx.strftime("%Y-%m-%d") if hasattr(idx, 'strftime') else str(idx)[:10]
            daily_closes[d][ticker] = row["close"]
    
    # For each ticker, find its first available price date and price
    ticker_first_price = {}
    ticker_first_date = {}
    for ticker in tickers:
        for date in all_dates:
            if ticker in daily_closes.get(date, {}):
                ticker_first_price[ticker] = daily_closes[date][ticker]
                ticker_first_date[ticker] = date
                break
    
    # Only include tickers that have at least one price
    valid_tickers = [t for t in tickers if t in ticker_first_price]
    if not valid_tickers:
        return []
    
    n_valid = len(valid_tickers)
    allocation_per_ticker = initial_capital / n_valid
    
    # Compute shares for each ticker at its first available price
    shares_per_ticker = {}
    for t in valid_tickers:
        price = ticker_first_price[t]
        shares = allocation_per_ticker / price  # fractional shares for accurate EW
        shares_per_ticker[t] = shares
    
    # Track equity daily
    equity_curve = []
    for date in all_dates:
        closes_today = daily_closes.get(date, {})
        market_value = 0.0
        for t, shares in shares_per_ticker.items():
            # Use current price if available, else carry forward last known price
            if t in closes_today:
                market_value += closes_today[t] * shares
            else:
                # Find last available close (carry forward)
                for prev_date in reversed(all_dates[:all_dates.index(date)]):
                    if t in daily_closes.get(prev_date, {}):
                        market_value += daily_closes[prev_date][t] * shares
                        break
        
        equity = market_value  # No cash in buy & hold (fully invested)
        equity_curve.append((date, equity))
    
    return equity_curve


def load_index_data_from_naver():
    """Fetch KOSPI, KOSPI200, KOSDAQ, KOSDAQ150 index data from Naver."""
    import requests
    import time
    
    # Naver fchart symbols
    symbols = {
        'KOSPI': 'KOSPI',
        'KOSPI200': 'KPI200',  # KOSPI 200 futures/index
        'KOSDAQ': 'KOSDAQ',
        'KOSDAQ150': 'KQ150',  # KOSDAQ 150 - try alternative
    }
    
    index_data = {}
    for name, symbol in symbols.items():
        try:
            url = f"https://fchart.stock.naver.com/sise.nhn?symbol={symbol}&timeframe=day&count=4000&requestType=0"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            candles = []
            for item in response.text.split('<item data="'):
                if not item:
                    continue
                data = item.split('"')[0]
                parts = data.split('|')
                if len(parts) >= 6:
                    date, open_p, high, low, close, volume = parts[:6]
                    candles.append({
                        'date': date,
                        'open': float(open_p),
                        'high': float(high),
                        'low': float(low),
                        'close': float(close),
                        'volume': int(volume)
                    })
            
            if candles:
                df = pd.DataFrame(candles)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').set_index('date')
                index_data[name] = df[['open', 'high', 'low', 'close', 'volume']]
                print(f"  {name}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")
            else:
                print(f"  {name}: No data")
                
            time.sleep(0.5)  # Rate limit
            
        except Exception as e:
            print(f"  {name}: Error - {e}")
    
    return index_data


def build_index_equity_curve(index_df, calendar, start_date, end_date, initial_capital=100_000_000):
    """Build equity curve for a single index."""
    all_dates = calendar.sessions_between(start_date, end_date)
    
    # Filter index data to date range
    idx = index_df[(index_df.index >= start_date) & (index_df.index <= end_date)]
    if idx.empty:
        return []
    
    # Build daily closes dict
    daily_closes = {}
    for dt, row in idx.iterrows():
        d = dt.strftime("%Y-%m-%d")
        daily_closes[d] = row['close']
    
    # Buy & hold: invest all capital on first available date
    first_date = all_dates[0]
    entry_price = None
    for d in all_dates:
        if d in daily_closes:
            entry_price = daily_closes[d]
            break
    
    if entry_price is None:
        return []
    
    shares = initial_capital / entry_price  # fractional shares for index
    equity_curve = []
    
    for date in all_dates:
        close_price = daily_closes.get(date)
        if close_price is None:
            # Carry forward last known price
            for prev_date in reversed(all_dates[:all_dates.index(date)]):
                if prev_date in daily_closes:
                    close_price = daily_closes[prev_date]
                    break
        
        if close_price:
            equity = shares * close_price
            equity_curve.append((date, equity))
    
    return equity_curve


def main():
    print("=" * 60)
    print("BENCHMARK ANALYSIS: TREND-BREAKOUT-v1 vs Market Indices")
    print("=" * 60)
    
    # Load strategy results
    print("\n[1/5] Loading strategy results...")
    pkl_path = "full_smoke_result.pkl"
    with open(pkl_path, 'rb') as f:
        result = pickle.load(f)
    
    portfolio = result['portfolio']
    bars_by_ticker = result['bars_by_ticker']
    calendar = result['calendar']
    universe = result['universe']
    
    strategy_tickers = universe.tickers
    print(f"  Strategy universe: {len(strategy_tickers)} tickers")
    print(f"  Price data: {len(bars_by_ticker)} tickers")
    
    # Load strategy annual returns (already computed)
    print("\n[2/5] Loading strategy annual returns...")
    strategy_annual_path = "reports/2026-08-15-trend-breakout-v1-annual-analysis-2154/v1.json"
    with open(strategy_annual_path, 'r', encoding='utf-8') as f:
        strategy_data = json.load(f)
    strategy_annual = strategy_data['annual']
    print(f"  Strategy years: {list(strategy_annual.keys())}")
    
    # Compute Strategy Universe Equal-Weight Buy & Hold
    print("\n[3/5] Computing Strategy Universe Equal-Weight Buy & Hold...")
    ew_equity = build_ew_equity_curve(
        bars_by_ticker, calendar, '2014-05-13', '2026-08-03'
    )
    ew_annual = compute_annual_returns(ew_equity)
    print(f"  EW equity curve: {len(ew_equity)} points")
    print(f"  EW years: {list(ew_annual.keys())}")
    
    # Fetch Market Index Data
    print("\n[4/5] Fetching market index data (KOSPI, KOSPI200, KOSDAQ, KOSDAQ150)...")
    index_data = load_index_data_from_naver()
    
    index_annual = {}
    for name, df in index_data.items():
        eq_curve = build_index_equity_curve(df, calendar, '2014-05-13', '2026-08-03')
        index_annual[name] = compute_annual_returns(eq_curve)
        print(f"  {name}: {len(eq_curve)} points, years={list(index_annual[name].keys())}")
    
    # Compile comparison
    print("\n[5/5] Compiling comparison...")
    
    all_years = sorted(set(
        list(strategy_annual.keys()) + 
        list(ew_annual.keys()) + 
        sum([list(v.keys()) for v in index_annual.values()], [])
    ))
    
    comparison = {}
    for year in all_years:
        comparison[year] = {"year": year}
        
        # Strategy
        if year in strategy_annual:
            s = strategy_annual[year]
            comparison[year]["strategy"] = {
                "annualReturn": s.get("annualReturn"),
                "maxDrawdown": s.get("maxDrawdown"),
                "cagr": s.get("cagr"),
                "sharpe": s.get("sharpe"),
                "tradeCount": s.get("tradeStats", {}).get("tradeCount"),
                "winRate": s.get("tradeStats", {}).get("winRate"),
            }
        
        # Strategy Universe EW
        if year in ew_annual:
            e = ew_annual[year]
            comparison[year]["universe_ew"] = {
                "annualReturn": e.get("annualReturn"),
                "maxDrawdown": e.get("maxDrawdown"),
                "cagr": e.get("cagr"),
                "sharpe": e.get("sharpe"),
            }
        
        # Market Indices
        for idx_name in ['KOSPI', 'KOSPI200', 'KOSDAQ', 'KOSDAQ150']:
            if idx_name in index_annual and year in index_annual[idx_name]:
                i = index_annual[idx_name][year]
                comparison[year][idx_name.lower()] = {
                    "annualReturn": i.get("annualReturn"),
                    "maxDrawdown": i.get("maxDrawdown"),
                    "cagr": i.get("cagr"),
                    "sharpe": i.get("sharpe"),
                }
        
        # Excess returns vs each benchmark
        if year in strategy_annual and 'annualReturn' in strategy_annual[year]:
            s_ret = strategy_annual[year]['annualReturn']
            for bm_name in ['universe_ew', 'kospi', 'kospi200', 'kosdaq', 'kosdaq150']:
                if bm_name in comparison[year] and 'annualReturn' in comparison[year][bm_name]:
                    bm_ret = comparison[year][bm_name]['annualReturn']
                    if s_ret is not None and bm_ret is not None:
                        comparison[year][f"excess_vs_{bm_name}"] = s_ret - bm_ret
    
    # Save results
    output_dir = "reports/2026-08-15-trend-breakout-v1-benchmark-analysis"
    os.makedirs(output_dir, exist_ok=True)
    
    output = {
        "strategyId": "trend_breakout_v1",
        "runClass": "SMOKE",
        "dataSource": "full_smoke_result.pkl (2,154 trades) + Naver fchart indices",
        "comparison": comparison,
        "metadata": {
            "strategyUniverse": "A1A_ONLY",
            "strategyTickers": len(strategy_tickers),
            "priceTickers": len(bars_by_ticker),
            "period": "2014-05-13 to 2026-08-03",
            "benchmarks": ["KOSPI", "KOSPI200", "KOSDAQ", "KOSDAQ150", "Universe EW"],
        }
    }
    
    output_path = os.path.join(output_dir, "benchmark_comparison.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved to {output_path}")
    
    # Print summary table
    print("\n" + "=" * 120)
    print("ANNUAL RETURN COMPARISON (%)")
    print("=" * 120)
    header = f"{'Year':>6} | {'Strategy':>10} | {'Univ EW':>10} | {'KOSPI':>10} | {'KOSPI200':>10} | {'KOSDAQ':>10} | {'KQ150':>10} | {'Excess vs EW':>12} | {'Excess vs KOSPI':>14}"
    print(header)
    print("-" * len(header))
    
    for year in all_years:
        if year not in comparison:
            continue
        c = comparison[year]
        
        s_ret = c.get('strategy', {}).get('annualReturn')
        ew_ret = c.get('universe_ew', {}).get('annualReturn')
        kospi_ret = c.get('kospi', {}).get('annualReturn')
        k200_ret = c.get('kospi200', {}).get('annualReturn')
        kq_ret = c.get('kosdaq', {}).get('annualReturn')
        kq150_ret = c.get('kosdaq150', {}).get('annualReturn')
        excess_ew = c.get('excess_vs_universe_ew')
        excess_kospi = c.get('excess_vs_kospi')
        
        def fmt(x):
            return f"{x*100:>9.2f}%" if x is not None else "     N/A"
        
        def fmt_ex(x):
            return f"{x*100:>+11.2f}%p" if x is not None else "       N/A"
        
        line = (f"{year:>6} | {fmt(s_ret)} | {fmt(ew_ret)} | {fmt(kospi_ret)} | "
                f"{fmt(k200_ret)} | {fmt(kq_ret)} | {fmt(kq150_ret)} | "
                f"{fmt_ex(excess_ew)} | {fmt_ex(excess_kospi)}")
        print(line)
    
    print("=" * 120)
    print("\nPositive excess = strategy outperformed benchmark")
    print("Negative excess = strategy underperformed benchmark")


if __name__ == "__main__":
    import pickle
    import requests
    main()