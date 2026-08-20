#!/usr/bin/env python
"""Reconstruct equity curve from closed positions and compute annual analysis for 2,154 trades."""
import sys
import os
import json
from datetime import date as _date
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.runner import run_smoke
from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe, sortino, calmar, trade_stats


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def reconstruct_equity_curve(portfolio, bars_by_ticker, calendar, start_date, end_date):
    """Reconstruct daily equity curve by replaying portfolio day by day."""
    # Get all trading dates in range
    all_dates = calendar.sessions_between(start_date, end_date)
    
    # Build daily closes for all symbols that appear in closed_positions
    symbols_needed = set()
    for pos in portfolio.closed_positions:
        symbols_needed.add(pos["symbol"])
    
    # Build daily closes dict: {date: {symbol: close}}
    daily_closes = defaultdict(dict)
    for symbol in symbols_needed:
        if symbol in bars_by_ticker:
            bars = bars_by_ticker[symbol]
            for idx, row in bars.iterrows():
                d = idx.strftime("%Y-%m-%d") if hasattr(idx, 'strftime') else str(idx)[:10]
                daily_closes[d][symbol] = row["close"]
    
    # Build position timeline: for each date, which positions are open
    # position: {symbol, entry_date, exit_date, shares, entry_price, cost_basis}
    # We need to track cash and positions day by day
    
    # First, organize trades by entry/exit date
    trades_by_entry = defaultdict(list)
    trades_by_exit = defaultdict(list)
    for pos in portfolio.closed_positions:
        trades_by_entry[pos["entry_date"]].append(pos)
        trades_by_exit[pos["exit_date"]].append(pos)
    
    # Replay portfolio day by day
    cash = 100_000_000.0  # initial capital
    open_positions = {}  # symbol -> {shares, cost_basis, entry_price, entry_date}
    equity_curve = []
    
    # Cost model parameters (from strategy params)
    params = {
        "entryCostBps": 5.0,
        "exitCostBps": 5.0,
        "slippageBps": 0.0,
    }
    
    for date in all_dates:
        # Process exits first (exits free up cash for next day's entries)
        if date in trades_by_exit:
            for pos in trades_by_exit[date]:
                symbol = pos["symbol"]
                if symbol in open_positions:
                    exit_price = pos["exit"].fill_price
                    shares = pos["shares"]
                    proceeds = exit_price * shares
                    exit_cost = proceeds * (params["exitCostBps"] / 10000)
                    cash += proceeds - exit_cost
                    # Remove position
                    del open_positions[symbol]
                # else: position was never admitted (shouldn't happen for closed_positions)
        
        # Process entries
        if date in trades_by_entry:
            for pos in trades_by_entry[date]:
                symbol = pos["symbol"]
                # Check if position was actually admitted (not all signals become positions)
                # The closed_positions only contains admitted positions
                entry_price = pos["entry"].fill_price
                shares = pos["shares"]
                cost_basis = pos["cost_basis"]
                entry_cost = cost_basis * (params["entryCostBps"] / 10000)
                # Verify we can afford it
                total_cost = cost_basis + entry_cost
                if total_cost <= cash:
                    cash -= total_cost
                    open_positions[symbol] = {
                        "shares": shares,
                        "cost_basis": cost_basis,
                        "entry_price": entry_price,
                        "entry_date": pos["entry_date"],
                    }
        
        # Compute equity at end of day
        market_value = 0.0
        closes_today = daily_closes.get(date, {})
        for symbol, pos_data in open_positions.items():
            close_price = closes_today.get(symbol, pos_data["entry_price"])
            market_value += close_price * pos_data["shares"]
        
        equity = cash + market_value
        equity_curve.append((date, equity))
    
    return equity_curve


def compute_annual_analysis(equity_curve, portfolio):
    """Compute annual breakdown from equity curve and closed positions."""
    if not equity_curve or len(equity_curve) < 2:
        return {}
    
    # Group equity curve by year
    yearly_equity = defaultdict(list)
    for d, eq in equity_curve:
        year = d[:4]
        yearly_equity[year].append((d, eq))
    
    # Group trades by year (based on exit date)
    yearly_trades = defaultdict(list)
    for pos in portfolio.closed_positions:
        exit_date = pos["exit_date"]
        year = exit_date[:4]
        yearly_trades[year].append({
            "pnl": pos["pnl"],
            "holding_sessions": 0,  # not stored, could compute from entry/exit
            "exit_type": pos["exit"].fill_type,
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
        exit_counts = defaultdict(int)
        for t in year_trades:
            exit_counts[t["exit_type"]] += 1
        exit_pct = {k: v/len(year_trades) for k, v in exit_counts.items()} if year_trades else {}
        
        annual[year] = {
            "startDate": start_date,
            "startEquity": start_eq,
            "endDate": end_date,
            "endEquity": end_eq,
            "annualReturn": ann_return,
            "maxDrawdown": ann_mdd,
            "cagr": ann_cagr,
            "sharpe": ann_sharpe,
            "sortino": ann_sortino,
            "calmar": ann_calmar,
            "tradeStats": t_stats,
            "exitTypeCounts": exit_pct,
        }
    
    return annual


def main():
    print("Running TREND-BREAKOUT-v1 full smoke (2,154 trades)...")
    result = run_smoke('trend_breakout_v1', '2014-05-13', '2026-08-03', 
                       'C:/Users/User/projects/stock')
    
    portfolio = result['portfolio']
    bars_by_ticker = result['bars_by_ticker']
    calendar = result['calendar']
    
    print(f"Closed positions: {len(portfolio.closed_positions)}")
    print(f"Bars tickers: {len(bars_by_ticker)}")
    
    # Reconstruct equity curve
    print("Reconstructing equity curve...")
    equity_curve = reconstruct_equity_curve(
        portfolio, bars_by_ticker, calendar, '2014-05-13', '2026-08-03'
    )
    
    print(f"Equity curve points: {len(equity_curve)}")
    if equity_curve:
        print(f"First: {equity_curve[0]}")
        print(f"Last: {equity_curve[-1]}")
    
    # Compute annual analysis
    print("Computing annual analysis...")
    annual = compute_annual_analysis(equity_curve, portfolio)
    
    # Save results
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