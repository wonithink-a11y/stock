#!/usr/bin/env python
"""Run TREND-BREAKOUT-v1 full smoke and compute annual analysis for 2,154 trades."""
import sys
import os
import json
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke
from engine.metrics.metrics import (
    total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats
)


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def compute_annual_analysis(portfolio, equity_curve):
    """Compute annual breakdown from portfolio closed positions and equity curve."""
    if not equity_curve or len(equity_curve) < 2:
        return {}
    
    # Group equity curve by year
    yearly_equity = {}
    for d, eq in equity_curve:
        year = d[:4]
        if year not in yearly_equity:
            yearly_equity[year] = []
        yearly_equity[year].append((d, eq))
    
    # Group trades by year (based on exit date)
    yearly_trades = {}
    for pos in portfolio.closed_positions:
        exit_date = pos["exit"]["fill_date"]
        year = exit_date[:4]
        if year not in yearly_trades:
            yearly_trades[year] = []
        yearly_trades[year].append({
            "pnl": pos["pnl"],
            "holding_sessions": pos.get("holding_sessions", 0),
            "exit_type": pos["exit"]["fill_type"],
        })
    
    annual = {}
    sorted_years = sorted(yearly_equity.keys())
    
    for i, year in enumerate(sorted_years):
        year_eq = yearly_equity[year]
        year_trades = yearly_trades.get(year, [])
        
        # Find start/end equity for this year
        if i == 0:
            start_eq = equity_curve[0][1]
            start_date = equity_curve[0][0]
        else:
            # Find last equity point of previous year
            prev_year = sorted_years[i-1]
            prev_eq = yearly_equity[prev_year]
            start_eq = prev_eq[-1][1]
            start_date = prev_eq[-1][0]
        
        end_eq = year_eq[-1][1]
        end_date = year_eq[-1][0]
        
        # Build equity curve for this year (include start point from prev year)
        year_equity_curve = [(start_date, start_eq)] + year_eq
        
        # Compute metrics
        ann_return = total_return(year_equity_curve)
        ann_cagr = cagr(year_equity_curve)
        ann_mdd = max_drawdown(year_equity_curve)
        ann_sharpe = sharpe(year_equity_curve)
        ann_sortino = sortino(year_equity_curve)
        ann_calmar = calmar(year_equity_curve)
        
        # Trade stats for this year
        t_stats = trade_stats(year_trades)
        
        # Exit type counts
        exit_counts = {}
        for t in year_trades:
            et = t["exit_type"]
            exit_counts[et] = exit_counts.get(et, 0) + 1
        exit_pct = {k: v/len(year_trades) for k, v in exit_counts.items()} if year_trades else {}
        
        annual[year] = {
            "startDate": start_date,
            "startEquity": start_eq,
            "endDate": end_date,
            "endEquity": end_eq,
            "annualReturn": ann_return,
            "maxDrawdown": ann_mdd,
            "tradeStats": t_stats,
            "exitTypeCounts": exit_pct,
        }
    
    return annual


def main():
    print("Running TREND-BREAKOUT-v1 full smoke (2,154 trades)...")
    result = run_smoke('trend_breakout_v1', '2014-05-13', '2026-08-03', 'C:/Users/User/projects/stock')
    
    portfolio = result['portfolio']
    print(f"Closed positions: {len(portfolio.closed_positions)}")
    print(f"Equity curve points: {len(portfolio.equity_curve) if hasattr(portfolio, 'equity_curve') else 0}")
    
    # The portfolio should have equity_curve attribute from the runner
    # Let's check the runner code... actually the runner builds equity curve in _schedule_portfolio
    # but doesn't seem to store it on portfolio. Let me check.
    
    # The runner returns equityCurvePoints, equityCurveFirst, equityCurveLast in diag
    # but not the full equity curve. We need to reconstruct it or get it from portfolio.
    
    # Check if portfolio has equity_curve
    if hasattr(portfolio, 'equity_curve'):
        equity_curve = portfolio.equity_curve
    else:
        # Reconstruct from diag? The diag only has first/last and point count
        # We need the full equity curve. Let me check the runner...
        print("WARNING: portfolio.equity_curve not found, checking diag...")
        print("Diag equityCurvePoints:", result['diag'].get('equityCurvePoints'))
        print("Diag equityCurveFirst:", result['diag'].get('equityCurveFirst'))
        print("Diag equityCurveLast:", result['diag'].get('equityCurveLast'))
        # We can't reconstruct annual without full equity curve
        return
    
    annual = compute_annual_analysis(portfolio, equity_curve)
    
    output_dir = "reports/2026-08-15-trend-breakout-v1-annual-analysis-2154"
    os.makedirs(output_dir, exist_ok=True)
    
    output = {
        "strategyId": "trend_breakout_v1",
        "runClass": "SMOKE",
        "dataSource": "runner full smoke 2026-08-15 post-fix (2,154 trades)",
        "annual": annual,
    }
    
    output_path = os.path.join(output_dir, "v1.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"Annual analysis saved to {output_path}")
    
    # Print summary
    for year, data in annual.items():
        print(f"\n{year}: Return={data['annualReturn']:.4%}, CAGR={data.get('cagr', 'N/A')}, "
              f"MDD={data['maxDrawdown']:.4%}, Trades={data['tradeStats']['tradeCount']}, "
              f"WinRate={data['tradeStats']['winRate']:.2%}, PF={data['tradeStats']['profitFactor']:.4f}")


if __name__ == "__main__":
    main()