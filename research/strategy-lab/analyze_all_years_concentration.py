#!/usr/bin/env python
"""Analyze concentration for all years 2014-2025 from existing full_smoke_result.pkl."""
import sys
import os
import json
import pickle
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def analyze_year(trades, year):
    """Analyze concentration for a specific year."""
    year_trades = [p for p in trades if p['exit_date'].startswith(str(year))]
    
    if not year_trades:
        return None
    
    total_pnl = sum(p['pnl'] for p in year_trades)
    
    # Per-ticker aggregation
    ticker_stats = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'wins': 0})
    
    for p in year_trades:
        ticker = p['symbol']
        pnl = p['pnl']
        ticker_stats[ticker]['pnl'] += pnl
        ticker_stats[ticker]['trades'] += 1
        if pnl > 0:
            ticker_stats[ticker]['wins'] += 1
    
    ticker_list = []
    for ticker, stats in ticker_stats.items():
        ticker_list.append({
            'ticker': ticker,
            'total_pnl': stats['pnl'],
            'trade_count': stats['trades'],
            'avg_pnl': stats['pnl'] / stats['trades'],
            'win_rate': stats['wins'] / stats['trades'] if stats['trades'] > 0 else 0,
        })
    
    ticker_list.sort(key=lambda x: x['total_pnl'], reverse=True)
    
    n_tickers = len(ticker_list)
    top_1_pct = ticker_list[0]['total_pnl'] / total_pnl if total_pnl != 0 else 0
    top_3_pct = sum(t['total_pnl'] for t in ticker_list[:3]) / total_pnl if total_pnl != 0 else 0
    top_10_pct_n = max(1, int(n_tickers * 0.10))
    top_10_pct = sum(t['total_pnl'] for t in ticker_list[:top_10_pct_n]) / total_pnl if total_pnl != 0 else 0
    
    # Monthly aggregation
    monthly_pnl = defaultdict(float)
    monthly_trades = defaultdict(int)
    for p in year_trades:
        month = p['exit_date'][:7]
        monthly_pnl[month] += p['pnl']
        monthly_trades[month] += 1
    
    max_month = max(monthly_pnl, key=monthly_pnl.get) if monthly_pnl else None
    max_month_pnl = monthly_pnl[max_month] if max_month else 0
    max_month_pct = max_month_pnl / total_pnl if total_pnl != 0 else 0
    
    # HHI for positive PnL
    positive_tickers = [t for t in ticker_list if t['total_pnl'] > 0]
    total_positive = sum(t['total_pnl'] for t in positive_tickers)
    hhi = sum((t['total_pnl'] / total_positive) ** 2 for t in positive_tickers) * 10000 if total_positive > 0 else 0
    
    return {
        'year': year,
        'total_trades': len(year_trades),
        'total_pnl': total_pnl,
        'n_tickers': n_tickers,
        'top_1_pct': top_1_pct,
        'top_3_pct': top_3_pct,
        'top_10_pct': top_10_pct,
        'top_1_ticker': ticker_list[0]['ticker'] if ticker_list else None,
        'top_1_pnl': ticker_list[0]['total_pnl'] if ticker_list else 0,
        'monthly_pnl': dict(monthly_pnl),
        'max_month': max_month,
        'max_month_pnl': max_month_pnl,
        'max_month_pct': max_month_pct,
        'hhi': hhi,
        'top_10_tickers': [
            {'rank': i+1, 'ticker': t['ticker'], 'pnl': t['total_pnl'], 'pnl_pct': t['total_pnl']/total_pnl if total_pnl!=0 else 0}
            for i, t in enumerate(ticker_list[:10])
        ]
    }


def main():
    print("Loading full_smoke_result.pkl...")
    with open('full_smoke_result.pkl', 'rb') as f:
        result = pickle.load(f)

    portfolio = result['portfolio']
    all_trades = portfolio.closed_positions
    
    print(f"Total closed trades: {len(all_trades)}")
    
    # Analyze all years
    years = list(range(2014, 2026))
    results = {}
    
    for year in years:
        print(f"\nAnalyzing {year}...")
        res = analyze_year(all_trades, year)
        if res:
            results[year] = res
            print(f"  Trades: {res['total_trades']}, PnL: {res['total_pnl']:,.0f}, "
                  f"Tickers: {res['n_tickers']}, Top1: {res['top_1_pct']*100:.1f}%, "
                  f"Top3: {res['top_3_pct']*100:.1f}%, MaxMonth: {res['max_month']} ({res['max_month_pct']*100:.1f}%)")
    
    # Summary comparison table
    print("\n" + "="*120)
    print("ANNUAL CONCENTRATION COMPARISON (2014-2025)")
    print("="*120)
    print(f"{'Year':>6} | {'Trades':>6} | {'PnL':>12} | {'Tickers':>7} | {'Top1%':>8} | {'Top3%':>8} | {'Top10%':>8} | {'MaxMonth':>8} | {'MaxMonth%':>9} | {'HHI':>6}")
    print("-"*120)
    
    for year in years:
        if year in results:
            r = results[year]
            print(f"{year:>6} | {r['total_trades']:>6} | {r['total_pnl']:>12,.0f} | {r['n_tickers']:>7} | "
                  f"{r['top_1_pct']*100:>7.1f}% | {r['top_3_pct']*100:>7.1f}% | {r['top_10_pct']*100:>7.1f}% | "
                  f"{r['max_month']:>8} | {r['max_month_pct']*100:>8.1f}% | {r['hhi']:>6.0f}")
    
    # Statistical comparison: 2025 vs 2014-2024
    print("\n" + "="*80)
    print("2025 vs 2014-2024 COMPARISON")
    print("="*80)
    
    past_years = [y for y in range(2014, 2025) if y in results]
    if past_years:
        metrics = ['top_1_pct', 'top_3_pct', 'top_10_pct', 'max_month_pct', 'hhi', 'total_pnl']
        for metric in metrics:
            past_vals = [results[y][metric] for y in past_years]
            past_mean = sum(past_vals) / len(past_vals)
            past_min = min(past_vals)
            past_max = max(past_vals)
            val_2025 = results[2025][metric] if 2025 in results else None
            
            if val_2025 is not None:
                z_score = (val_2025 - past_mean) / (max(past_max - past_min, 1e-6) / 2) if past_max != past_min else 0
                print(f"  {metric}: 2025={val_2025*100:.1f}% vs past avg={past_mean*100:.1f}% "
                      f"[{past_min*100:.1f}%, {past_max*100:.1f}%] z={z_score:.2f}")
    
    # Save results
    output = {
        'analysis_date': '2026-08-16',
        'source': 'full_smoke_result.pkl (2,154 trades, post-fix baseline)',
        'years_analyzed': years,
        'results': results
    }
    
    output_dir = "reports/2026-08-15-trend-breakout-v1-benchmark-analysis"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "all_years_concentration_analysis.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {output_path}")
    
    # Final judgment
    print("\n" + "="*80)
    print("JUDGMENT")
    print("="*80)
    
    if 2025 in results:
        r25 = results[2025]
        
        # ① 2025년 수익 집중도가 과거에도 반복됐는가?
        past_top1 = [results[y]['top_1_pct'] for y in past_years]
        past_top3 = [results[y]['top_3_pct'] for y in past_years]
        past_maxmonth = [results[y]['max_month_pct'] for y in past_years]
        
        print(f"\n① 2025년의 수익 집중도가 과거에도 반복됐는가?")
        print(f"   Top 1 종목 비중: 2025={r25['top_1_pct']*100:.1f}% vs 과거 평균={sum(past_top1)/len(past_top1)*100:.1f}% "
              f"[최소={min(past_top1)*100:.1f}%, 최대={max(past_top1)*100:.1f}%]")
        print(f"   Top 3 종목 비중: 2025={r25['top_3_pct']*100:.1f}% vs 과거 평균={sum(past_top3)/len(past_top3)*100:.1f}% "
              f"[최소={min(past_top3)*100:.1f}%, 최대={max(past_top3)*100:.1f}%]")
        print(f"   최대 월 비중: 2025={r25['max_month_pct']*100:.1f}% vs 과거 평균={sum(past_maxmonth)/len(past_maxmonth)*100:.1f}% "
              f"[최소={min(past_maxmonth)*100:.1f}%, 최대={max(past_maxmonth)*100:.1f}%]")
        
        # ② 2025년이 통계적으로/구조적으로 특별해 보이는가?
        is_outlier = (
            r25['top_1_pct'] > max(past_top1) or
            r25['top_3_pct'] > max(past_top3) or
            r25['max_month_pct'] > max(past_maxmonth)
        )
        print(f"\n② 2025년이 통계적으로/구조적으로 특별해 보이는가?")
        print(f"   Top 1 비중 과거 최대 초과: {r25['top_1_pct'] > max(past_top1)} (2025={r25['top_1_pct']*100:.1f}% vs 과거최대={max(past_top1)*100:.1f}%)")
        print(f"   Top 3 비중 과거 최대 초과: {r25['top_3_pct'] > max(past_top3)} (2025={r25['top_3_pct']*100:.1f}% vs 과거최대={max(past_top3)*100:.1f}%)")
        print(f"   최대 월 비중 과거 최대 초과: {r25['max_month_pct'] > max(past_maxmonth)} (2025={r25['max_month_pct']*100:.1f}% vs 과거최대={max(past_maxmonth)*100:.1f}%)")
        print(f"   → 종합: {'특이치(Outlier) 의심' if is_outlier else '과거 범위 내'}")
        
        # ③ 2025년 +107.77%를 전략의 일반적인 기대수익으로 볼 근거가 있는가?
        print(f"\n③ 현재 결과에서 2025년 +107.77%를 전략의 일반적인 기대수익으로 볼 근거가 있는가?")
        past_pnl = [results[y]['total_pnl'] for y in past_years if results[y]['total_pnl'] != 0]
        past_returns = [results[y]['total_pnl'] / 100000000 for y in past_years]  # rough return on 100M capital
        
        # Check if 2025 is outlier in PnL too
        is_pnl_outlier = r25['total_pnl'] > max(past_pnl) if past_pnl else True
        print(f"   2025 순수익({r25['total_pnl']:,.0f})이 과거 최대({max(past_pnl):,.0f}) 초과: {is_pnl_outlier}")
        print(f"   과거 연도 순수익 범위: {min(past_pnl):,.0f} ~ {max(past_pnl):,.0f}")
        print(f"   과거 연도 평균 순수익: {sum(past_pnl)/len(past_pnl):,.0f}")
        
        print(f"\n   → 결론: {'2025년은 예외적(outlier)이며 일반적인 기대수익으로 해석 불가' if is_outlier else '과거 분포 내에 있으나 상위권'}")
        print(f"   → 일반화 위험: 단일 연도(2025) 성과를 전략의 상수로 간주하면 과대평가 위험 큼")


if __name__ == "__main__":
    main()