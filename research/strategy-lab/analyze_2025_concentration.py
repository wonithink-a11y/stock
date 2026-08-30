#!/usr/bin/env python
"""Analyze 2025 return concentration from existing full_smoke_result.pkl."""
import sys
import os
import json
import pickle
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    print("Loading full_smoke_result.pkl...")
    with open('full_smoke_result.pkl', 'rb') as f:
        result = pickle.load(f)

    portfolio = result['portfolio']
    
    # Extract 2025 closed trades
    trades_2025 = [p for p in portfolio.closed_positions if p['exit_date'].startswith('2025')]
    print(f"2025 closed trades: {len(trades_2025)}")
    
    if not trades_2025:
        print("No 2025 trades found!")
        return
    
    # Total PnL
    total_pnl = sum(p['pnl'] for p in trades_2025)
    print(f"Total 2025 PnL: {total_pnl:,.0f}")
    
    # Per-ticker aggregation
    ticker_stats = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'wins': 0, 'monthly': defaultdict(float)})
    
    for p in trades_2025:
        ticker = p['symbol']
        pnl = p['pnl']
        month = p['exit_date'][:7]
        
        ticker_stats[ticker]['pnl'] += pnl
        ticker_stats[ticker]['trades'] += 1
        ticker_stats[ticker]['monthly'][month] += pnl
        if pnl > 0:
            ticker_stats[ticker]['wins'] += 1
    
    # Convert to list for sorting
    ticker_list = []
    for ticker, stats in ticker_stats.items():
        ticker_list.append({
            'ticker': ticker,
            'total_pnl': stats['pnl'],
            'trade_count': stats['trades'],
            'avg_pnl': stats['pnl'] / stats['trades'],
            'win_rate': stats['wins'] / stats['trades'] if stats['trades'] > 0 else 0,
            'monthly': dict(stats['monthly'])
        })
    
    # Sort by total PnL descending
    ticker_list.sort(key=lambda x: x['total_pnl'], reverse=True)
    
    # Concentration analysis
    total_positive_pnl = sum(t['total_pnl'] for t in ticker_list if t['total_pnl'] > 0)
    total_negative_pnl = sum(t['total_pnl'] for t in ticker_list if t['total_pnl'] < 0)
    print(f"Total positive PnL: {total_positive_pnl:,.0f}")
    print(f"Total negative PnL: {total_negative_pnl:,.0f}")
    print(f"Net PnL: {total_pnl:,.0f}")
    
    n_tickers = len(ticker_list)
    top_5_pct = max(1, int(n_tickers * 0.05))
    top_10_pct = max(1, int(n_tickers * 0.10))
    top_20_pct = max(1, int(n_tickers * 0.20))
    
    top_5_pnl = sum(t['total_pnl'] for t in ticker_list[:top_5_pct])
    top_10_pnl = sum(t['total_pnl'] for t in ticker_list[:top_10_pct])
    top_20_pnl = sum(t['total_pnl'] for t in ticker_list[:top_20_pct])
    
    print(f"\n=== Concentration Analysis ===")
    print(f"Total tickers traded in 2025: {n_tickers}")
    print(f"Top 5% ({top_5_pct} tickers) PnL share: {top_5_pnl/total_pnl*100:.1f}% ({top_5_pnl:,.0f})")
    print(f"Top 10% ({top_10_pct} tickers) PnL share: {top_10_pnl/total_pnl*100:.1f}% ({top_10_pnl:,.0f})")
    print(f"Top 20% ({top_20_pct} tickers) PnL share: {top_20_pnl/total_pnl*100:.1f}% ({top_20_pnl:,.0f})")
    
    # Top 10 tickers
    print(f"\n=== Top 10 Tickers by PnL ===")
    for i, t in enumerate(ticker_list[:10], 1):
        pnl_share = t['total_pnl'] / total_pnl * 100
        print(f"  {i}. {t['ticker']}: PnL={t['total_pnl']:>12,.0f} ({pnl_share:.1f}%), "
              f"trades={t['trade_count']}, avg={t['avg_pnl']:>10,.0f}, "
              f"win%={t['win_rate']:.1%}")
    
    # Monthly aggregation
    monthly_pnl = defaultdict(float)
    monthly_trades = defaultdict(int)
    for p in trades_2025:
        month = p['exit_date'][:7]
        monthly_pnl[month] += p['pnl']
        monthly_trades[month] += 1
    
    print(f"\n=== Monthly PnL ===")
    for month in sorted(monthly_pnl.keys()):
        pnl = monthly_pnl[month]
        n = monthly_trades[month]
        pnl_share = pnl / total_pnl * 100
        print(f"  {month}: PnL={pnl:>12,.0f} ({pnl_share:.1f}%), trades={n}")
    
    # Concentration by month (top month share)
    max_month_pnl = max(monthly_pnl.values())
    max_month = max(monthly_pnl, key=monthly_pnl.get)
    print(f"\nMax monthly PnL: {max_month} = {max_month_pnl:,.0f} ({max_month_pnl/total_pnl*100:.1f}%)")
    
    # Herfindahl-Hirschman Index for tickers (concentration measure)
    # HHI = sum((ticker_pnl / total_pnl)^2) * 10000
    # Only for positive PnL contributors
    positive_tickers = [t for t in ticker_list if t['total_pnl'] > 0]
    if positive_tickers:
        hhi = sum((t['total_pnl'] / total_positive_pnl) ** 2 for t in positive_tickers) * 10000
        print(f"\nHHI (positive PnL tickers): {hhi:.0f}")
        print(f"  > 2500 = highly concentrated, 1500-2500 = moderately concentrated, < 1500 = unconcentrated")
    
    # Save results
    output = {
        "period": "2025",
        "total_trades": len(trades_2025),
        "total_pnl": total_pnl,
        "total_positive_pnl": total_positive_pnl,
        "total_negative_pnl": total_negative_pnl,
        "n_tickers": n_tickers,
        "concentration": {
            "top_5_pct_share": top_5_pnl / total_pnl,
            "top_10_pct_share": top_10_pnl / total_pnl,
            "top_20_pct_share": top_20_pnl / total_pnl,
            "top_5_pct_count": top_5_pct,
            "top_10_pct_count": top_10_pct,
            "top_20_pct_count": top_20_pct,
            "hhi_positive": hhi if positive_tickers else None
        },
        "top_10_tickers": [
            {
                "rank": i,
                "ticker": t['ticker'],
                "total_pnl": t['total_pnl'],
                "pnl_share": t['total_pnl'] / total_pnl,
                "trade_count": t['trade_count'],
                "avg_pnl": t['avg_pnl'],
                "win_rate": t['win_rate']
            }
            for i, t in enumerate(ticker_list[:10], 1)
        ],
        "monthly_pnl": {
            month: {
                "pnl": monthly_pnl[month],
                "trade_count": monthly_trades[month],
                "pnl_share": monthly_pnl[month] / total_pnl
            }
            for month in sorted(monthly_pnl.keys())
        },
        "max_monthly_pnl_share": max_month_pnl / total_pnl,
        "max_month": max_month
    }
    
    output_dir = "reports/2026-08-15-trend-breakout-v1-benchmark-analysis"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "2025_concentration_analysis.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {output_path}")
    
    # Return for final judgment
    return output


if __name__ == "__main__":
    result = main()
    
    if result:
        print("\n" + "="*60)
        print("JUDGMENT:")
        print("="*60)
        
        conc = result['concentration']
        print(f"① 2025년 수익이 소수 종목에 집중됐는가?")
        print(f"   Top 10% 종목({conc['top_10_pct_count']}개) 수익 비중: {conc['top_10_pct_share']*100:.1f}%")
        print(f"   Top 20% 종목({conc['top_20_pct_count']}개) 수익 비중: {conc['top_20_pct_share']*100:.1f}%")
        if conc['hhi_positive']:
            print(f"   HHI (양수 PnL 종목): {conc['hhi_positive']:.0f} "
                  f"{'→ 고도로 집중' if conc['hhi_positive'] > 2500 else '→ 중간 집중' if conc['hhi_positive'] > 1500 else '→ 비집중'}")
        
        print(f"\n② 특정 월에 수익이 집중됐는가?")
        print(f"   최대 월 수익 비중: {result['max_monthly_pnl_share']*100:.1f}% ({result['max_month']})")
        
        print(f"\n③ +107.77%를 전략의 일반적인 성과로 해석해도 되는가?")
        print(f"   → 종목/월 집중도와 HHI를 종합 판단 필요")