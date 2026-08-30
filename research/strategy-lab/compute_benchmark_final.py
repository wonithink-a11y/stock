#!/usr/bin/env python
"""Final benchmark comparison: TREND-BREAKOUT-v1 vs Market Indices + Universe EW."""
import sys
import os
import json
import pandas as pd

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


def load_index_data_from_naver():
    """Fetch KOSPI, KOSPI200, KOSDAQ index data from Naver."""
    import requests
    import time
    
    symbols = {
        'KOSPI': 'KOSPI',
        'KOSPI200': 'KPI200',
        'KOSDAQ': 'KOSDAQ',
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
                
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  {name}: Error - {e}")
    
    return index_data


def build_index_equity_curve(index_df, calendar, start_date, end_date, initial_capital=100_000_000):
    """Build equity curve for a single index."""
    all_dates = calendar.sessions_between(start_date, end_date)
    all_dates_str = [d if isinstance(d, str) else d.strftime('%Y-%m-%d') for d in all_dates]
    
    idx = index_df[(index_df.index >= start_date) & (index_df.index <= end_date)]
    if idx.empty:
        return []
    
    daily_closes = {}
    for dt, row in idx.iterrows():
        d = dt.strftime("%Y-%m-%d")
        daily_closes[d] = row['close']
    
    first_date = all_dates[0]
    entry_price = None
    for d in all_dates_str:
        if d in daily_closes:
            entry_price = daily_closes[d]
            break
    
    if entry_price is None:
        return []
    
    shares = initial_capital / entry_price
    equity_curve = []
    
    for date in all_dates_str:
        close_price = daily_closes.get(date)
        if close_price is None:
            for prev_date in reversed(all_dates_str[:all_dates_str.index(date)]):
                if prev_date in daily_closes:
                    close_price = daily_closes[prev_date]
                    break
        
        if close_price:
            equity = shares * close_price
            equity_curve.append((date, equity))
    
    return equity_curve


def main():
    print("=" * 70)
    print("BENCHMARK COMPARISON: TREND-BREAKOUT-v1 vs Market Indices + EW")
    print("=" * 70)
    
    # Load strategy results
    print("\n[1/5] Loading strategy results...")
    with open('full_smoke_result.pkl', 'rb') as f:
        result = pickle.load(f)
    
    portfolio = result['portfolio']
    calendar = result['calendar']
    universe = result['universe']
    
    # Load strategy annual returns
    print("[2/5] Loading strategy annual returns...")
    with open('reports/2026-08-15-trend-breakout-v1-annual-analysis-2154/v1.json', 'r', encoding='utf-8') as f:
        strategy_data = json.load(f)
    strategy_annual = strategy_data['annual']
    
    # Load Universe EW benchmark
    print("[3/5] Loading Universe EW benchmark...")
    with open('reports/2026-08-15-trend-breakout-v1-benchmark-analysis/universe_ew_benchmark.json', 'r', encoding='utf-8') as f:
        ew_data = json.load(f)
    ew_annual = ew_data['annual']
    
    # Fetch Market Index Data
    print("[4/5] Fetching market index data...")
    index_data = load_index_data_from_naver()
    
    index_annual = {}
    for name, df in index_data.items():
        eq_curve = build_index_equity_curve(df, calendar, '2014-05-15', '2026-08-03')
        index_annual[name] = compute_annual_returns(eq_curve)
        print(f"  {name}: {len(eq_curve)} points, years={list(index_annual[name].keys())}")
    
    # Compile comparison
    print("[5/5] Compiling comparison...")
    
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
        
        # Universe EW
        if year in ew_annual:
            e = ew_annual[year]
            comparison[year]["universe_ew"] = {
                "annualReturn": e.get("annualReturn"),
                "maxDrawdown": e.get("maxDrawdown"),
                "cagr": e.get("cagr"),
                "sharpe": e.get("sharpe"),
            }
        
        # Market Indices
        for idx_name in ['KOSPI', 'KOSPI200', 'KOSDAQ']:
            if idx_name in index_annual and year in index_annual[idx_name]:
                i = index_annual[idx_name][year]
                comparison[year][idx_name.lower()] = {
                    "annualReturn": i.get("annualReturn"),
                    "maxDrawdown": i.get("maxDrawdown"),
                    "cagr": i.get("cagr"),
                    "sharpe": i.get("sharpe"),
                }
        
        # Excess returns
        if year in strategy_annual and 'annualReturn' in strategy_annual[year]:
            s_ret = strategy_annual[year]['annualReturn']
            for bm_name in ['universe_ew', 'kospi', 'kospi200', 'kosdaq']:
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
        "dataSource": "full_smoke_result.pkl (2,154 trades) + Naver fchart indices + Universe EW",
        "comparison": comparison,
        "metadata": {
            "strategyUniverse": "A1A_ONLY",
            "strategyTickers": len(universe.tickers),
            "period": "2014-05-15 to 2026-08-03",
            "benchmarks": ["KOSPI", "KOSPI200", "KOSDAQ", "Universe EW"],
            "note": "Period starts 2014-05-15 (first date with ~1500 tickers). Strategy first signal: 2014-06-16.",
        }
    }
    
    output_path = os.path.join(output_dir, "benchmark_comparison_final.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\nResults saved to {output_path}")
    
    # Print summary table
    print("\n" + "=" * 130)
    print("ANNUAL RETURN COMPARISON (%)")
    print("=" * 130)
    header = f"{'Year':>6} | {'Strategy':>10} | {'Univ EW':>10} | {'KOSPI':>10} | {'KOSPI200':>10} | {'KOSDAQ':>10} | {'Ex vs EW':>12} | {'Ex vs KOSPI':>14} | {'Ex vs K200':>14} | {'Ex vs KQ':>12}"
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
        excess_ew = c.get('excess_vs_universe_ew')
        excess_kospi = c.get('excess_vs_kospi')
        excess_k200 = c.get('excess_vs_kospi200')
        excess_kq = c.get('excess_vs_kosdaq')
        
        def fmt(x):
            return f"{x*100:>9.2f}%" if x is not None else "     N/A"
        
        def fmt_ex(x):
            return f"{x*100:>+11.2f}%p" if x is not None else "       N/A"
        
        line = (f"{year:>6} | {fmt(s_ret)} | {fmt(ew_ret)} | {fmt(kospi_ret)} | "
                f"{fmt(k200_ret)} | {fmt(kq_ret)} | {fmt_ex(excess_ew)} | "
                f"{fmt_ex(excess_kospi)} | {fmt_ex(excess_k200)} | {fmt_ex(excess_kq)}")
        print(line)
    
    print("=" * 130)
    print("\nPositive excess = strategy outperformed benchmark")
    print("Negative excess = strategy underperformed benchmark")
    
    # 2025 specific analysis
    print("\n" + "=" * 70)
    print("2025 DEEP DIVE")
    print("=" * 70)
    if '2025' in comparison:
        c = comparison['2025']
        s_ret = c.get('strategy', {}).get('annualReturn')
        ew_ret = c.get('universe_ew', {}).get('annualReturn')
        kospi_ret = c.get('kospi', {}).get('annualReturn')
        k200_ret = c.get('kospi200', {}).get('annualReturn')
        kq_ret = c.get('kosdaq', {}).get('annualReturn')
        
        print(f"Strategy return:     {s_ret*100:.2f}%")
        print(f"Universe EW return:  {ew_ret*100:.2f}%  (excess: {(s_ret-ew_ret)*100:+.2f}%p)")
        print(f"KOSPI return:        {kospi_ret*100:.2f}%  (excess: {(s_ret-kospi_ret)*100:+.2f}%p)")
        print(f"KOSPI200 return:     {k200_ret*100:.2f}%  (excess: {(s_ret-k200_ret)*100:+.2f}%p)")
        print(f"KOSDAQ return:       {kq_ret*100:.2f}%  (excess: {(s_ret-kq_ret)*100:+.2f}%p)")
        
        # Check if strategy return is explained by market beta
        if s_ret > ew_ret and s_ret > kospi_ret and s_ret > k200_ret and s_ret > kq_ret:
            print("\n>>> Strategy OUTPERFORMED all benchmarks in 2025")
            print(">>> Excess return NOT fully explained by market beta")
        elif s_ret > 0 and max(ew_ret, kospi_ret, k200_ret, kq_ret) > 0:
            print("\n>>> Strategy return directionally aligned with market")
            print(">>> Part of return may be attributable to market beta")
        else:
            print("\n>>> Mixed signals - detailed attribution needed")


if __name__ == "__main__":
    import pickle
    import requests
    import time
    main()