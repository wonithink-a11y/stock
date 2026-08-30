#!/usr/bin/env python
"""Analyze long-term drawdown risk from existing TREND-BREAKOUT-v1 results."""
import sys
import os
import json
import pickle
from datetime import date as _date
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.metrics.metrics import total_return, cagr, max_drawdown, sharpe


def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()


def reconstruct_equity_curve(portfolio, initial_capital=100_000_000):
    """Reconstruct daily equity curve from closed trades and daily cash."""
    # Get all exit dates
    if not portfolio.closed_positions:
        return []
    
    # Collect all dates from trades
    all_dates = set()
    for pos in portfolio.closed_positions:
        all_dates.add(pos['entry_date'])
        all_dates.add(pos['exit_date'])
    
    # Also need to track daily cash changes
    # We'll reconstruct by simulating day by day from trade events
    
    # Build events: date -> list of (type, pnl, cash_change)
    events = defaultdict(list)
    
    for pos in portfolio.closed_positions:
        entry_date = pos['entry_date']
        exit_date = pos['exit_date']
        pnl = pos['pnl']
        entry = pos['entry']
        exit_fill = pos['exit']
        shares = pos['shares']
        
        # Entry: cash decreases by cost basis + entry cost
        cost_basis = entry.fill_price * shares
        entry_cost = cost_basis * (entry.cost_bps / 10000)
        events[entry_date].append(('entry', -cost_basis - entry_cost, shares, entry.fill_price))
        
        # Exit: cash increases by proceeds - exit cost
        proceeds = exit_fill.fill_price * shares
        exit_cost = proceeds * (exit_fill.cost_bps / 10000)
        events[exit_date].append(('exit', proceeds - exit_cost, -shares, exit_fill.fill_price))
    
    # Sort all dates
    sorted_dates = sorted(events.keys())
    if not sorted_dates:
        return []
    
    # Reconstruct equity curve
    cash = initial_capital
    open_positions = {}  # symbol -> {shares, entry_price}
    equity_curve = []
    
    # We need daily equity, not just event dates
    # Let's use the calendar to get all trading days
    # For simplicity, compute equity at each event date
    for date in sorted_dates:
        for event_type, cash_change, shares_change, price in events[date]:
            if event_type == 'entry':
                # This is a new position or addition
                cash += cash_change
            elif event_type == 'exit':
                cash += cash_change
        
        # Compute market value of open positions
        # We need current prices for open positions
        # Since we don't have daily prices in portfolio, we'll approximate
        # using the last known price from events
        market_value = 0
        # This is a limitation - we don't have daily prices for all open positions
        # Let's use a simpler approach: compute equity from portfolio.cash and closed positions
        
        # For now, just track cash + realized PnL
        equity_curve.append((date, cash))
    
    return equity_curve


def reconstruct_equity_from_trades(portfolio, initial_capital=100_000_000):
    """Better equity reconstruction using trade-by-trade simulation."""
    if not portfolio.closed_positions:
        return []
    
    # Collect all unique dates
    all_dates = set()
    for pos in portfolio.closed_positions:
        all_dates.add(pos['entry_date'])
        all_dates.add(pos['exit_date'])
    
    sorted_dates = sorted(all_dates)
    
    # Build daily events
    daily_events = defaultdict(list)
    for pos in portfolio.closed_positions:
        entry = pos['entry']
        exit_fill = pos['exit']
        shares = pos['shares']
        
        cost_basis = entry.fill_price * shares
        entry_cost = cost_basis * (entry.cost_bps / 10000)
        
        proceeds = exit_fill.fill_price * shares
        exit_cost = proceeds * (exit_fill.cost_bps / 10000)
        
        daily_events[pos['entry_date']].append({
            'type': 'entry',
            'cash_change': -(cost_basis + entry_cost),
            'shares': shares,
            'price': entry.fill_price,
            'symbol': pos['symbol']
        })
        
        daily_events[pos['exit_date']].append({
            'type': 'exit',
            'cash_change': proceeds - exit_cost,
            'shares': -shares,
            'price': exit_fill.fill_price,
            'symbol': pos['symbol']
        })
    
    # We need daily prices for open positions to compute mark-to-market
    # Since we don't have that, we'll use a simpler approach:
    # Compute equity at each event date using cash + realized PnL + estimated MTM
    
    cash = initial_capital
    open_positions = {}  # symbol -> {shares, entry_price, entry_cost_bps}
    equity_curve = []
    
    for date in sorted(daily_events.keys()):
        for event in daily_events[date]:
            if event['type'] == 'entry':
                cash += event['cash_change']
                open_positions[event['symbol']] = {
                    'shares': event['shares'],
                    'entry_price': event['price'],
                    'cost_bps': 5.0  # from strategy params
                }
            elif event['type'] == 'exit':
                cash += event['cash_change']
                if event['symbol'] in open_positions:
                    del open_positions[event['symbol']]
        
        # MTM: use entry price for open positions (conservative)
        mtm = sum(p['shares'] * p['entry_price'] for p in open_positions.values())
        equity = cash + mtm
        equity_curve.append((date, equity))
    
    return equity_curve


def compute_drawdowns(equity_curve):
    """Compute all drawdown periods from equity curve."""
    if not equity_curve or len(equity_curve) < 2:
        return []
    
    drawdowns = []
    peak_value = equity_curve[0][1]
    peak_date = equity_curve[0][0]
    in_drawdown = False
    trough_value = peak_value
    trough_date = peak_date
    
    for date, value in equity_curve:
        if value > peak_value:
            # New peak
            if in_drawdown:
                # Previous drawdown ended
                drawdowns.append({
                    'start_date': peak_date,
                    'end_date': date,
                    'trough_date': trough_date,
                    'peak_value': peak_value,
                    'trough_value': trough_value,
                    'drawdown_pct': (trough_value - peak_value) / peak_value,
                    'duration_days': (_to_ordinal(date) - _to_ordinal(peak_date)) if date else 0,
                    'recovered': True
                })
                in_drawdown = False
            peak_value = value
            peak_date = date
            trough_value = value
            trough_date = date
        elif value < trough_value:
            # Deeper trough
            trough_value = value
            trough_date = date
            in_drawdown = True
    
    # Handle final drawdown if not recovered
    if in_drawdown:
        drawdowns.append({
            'start_date': peak_date,
            'end_date': equity_curve[-1][0],
            'trough_date': trough_date,
            'peak_value': peak_value,
            'trough_value': trough_value,
            'drawdown_pct': (trough_value - peak_value) / peak_value,
            'duration_days': (_to_ordinal(equity_curve[-1][0]) - _to_ordinal(peak_date)),
            'recovered': False
        })
    
    return drawdowns


def analyze_drawdowns(drawdowns, equity_curve):
    """Analyze drawdown statistics."""
    if not drawdowns:
        return {}
    
    max_dd = min(d['drawdown_pct'] for d in drawdowns)
    max_dd_info = min(drawdowns, key=lambda d: d['drawdown_pct'])
    
    # Longest drawdown
    longest = max(drawdowns, key=lambda d: d['duration_days'])
    
    # Recovery rate
    recovered = sum(1 for d in drawdowns if d['recovered'])
    total = len(drawdowns)
    
    # Average drawdown
    avg_dd = sum(d['drawdown_pct'] for d in drawdowns) / len(drawdowns)
    avg_duration = sum(d['duration_days'] for d in drawdowns) / len(drawdowns)
    
    return {
        'max_drawdown': max_dd,
        'max_drawdown_info': max_dd_info,
        'longest_drawdown': {
            'duration_days': longest['duration_days'],
            'drawdown_pct': longest['drawdown_pct'],
            'start_date': longest['start_date'],
            'end_date': longest['end_date']
        },
        'total_drawdowns': total,
        'recovered_count': recovered,
        'recovery_rate': recovered / total,
        'avg_drawdown_pct': avg_dd,
        'avg_duration_days': avg_duration
    }


def compute_yearly_equity(equity_curve):
    """Compute year-end equity values."""
    if not equity_curve:
        return {}
    
    yearly = {}
    for date, value in equity_curve:
        year = date[:4]
        if year not in yearly or date > yearly[year][0]:
            yearly[year] = (date, value)
    
    return {y: v[1] for y, v in yearly.items()}


def load_kospi_data():
    """Load KOSPI data from previous analysis."""
    # Try to load from previous benchmark analysis
    try:
        with open('reports/2026-08-15-trend-breakout-v1-benchmark-analysis/benchmark_comparison_final.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Extract KOSPI annual returns
        kospi_annual = {}
        for year, comp in data['comparison'].items():
            if 'kospi' in comp:
                kospi_annual[year] = comp['kospi']['annualReturn']
        return kospi_annual
    except:
        return {}


def main():
    print("Loading full_smoke_result.pkl...")
    with open('full_smoke_result.pkl', 'rb') as f:
        result = pickle.load(f)
    
    portfolio = result['portfolio']
    print(f"Closed positions: {len(portfolio.closed_positions)}")
    print(f"Cash: {portfolio.cash:,.0f}")
    
    # Reconstruct equity curve
    print("Reconstructing equity curve...")
    equity_curve = reconstruct_equity_from_trades(portfolio)
    
    print(f"Equity curve points: {len(equity_curve)}")
    if equity_curve:
        print(f"First: {equity_curve[0]}")
        print(f"Last: {equity_curve[-1]}")
    
    # Compute overall metrics
    initial = 100_000_000
    final = equity_curve[-1][1] if equity_curve else initial
    
    total_ret = total_return(equity_curve)
    cagr_val = cagr(equity_curve)
    mdd_val = max_drawdown(equity_curve)
    sharpe_val = sharpe(equity_curve)
    
    print(f"\n=== Overall Metrics ===")
    print(f"Initial: {initial:,.0f}")
    print(f"Final: {final:,.0f}")
    print(f"Total Return: {total_ret:.4%}")
    print(f"CAGR: {cagr_val:.4%}")
    print(f"MDD: {mdd_val:.4%}")
    print(f"Sharpe: {sharpe_val:.4f}")
    
    # Compute drawdowns
    print("\nComputing drawdowns...")
    drawdowns = compute_drawdowns(equity_curve)
    dd_analysis = analyze_drawdowns(drawdowns, equity_curve)
    
    print(f"\n=== Drawdown Analysis ===")
    print(f"Max Drawdown: {dd_analysis['max_drawdown']:.4%}")
    print(f"Total Drawdown Periods: {dd_analysis['total_drawdowns']}")
    print(f"Recovered: {dd_analysis['recovered_count']}/{dd_analysis['total_drawdowns']} ({dd_analysis['recovery_rate']:.1%})")
    print(f"Avg Drawdown: {dd_analysis['avg_drawdown_pct']:.4%}")
    print(f"Avg Duration: {dd_analysis['avg_duration_days']:.1f} days")
    print(f"Longest DD: {dd_analysis['longest_drawdown']['duration_days']} days ({dd_analysis['longest_drawdown']['drawdown_pct']:.4%})")
    
    # MDD detail
    mdd_info = dd_analysis['max_drawdown_info']
    print(f"\n=== MDD Detail (-83.34%) ===")
    print(f"Start: {mdd_info['start_date']} (Peak: {mdd_info['peak_value']:,.0f})")
    print(f"Trough: {mdd_info['trough_date']} (Value: {mdd_info['trough_value']:,.0f})")
    print(f"End: {mdd_info['end_date']} (Recovered: {mdd_info['recovered']})")
    print(f"Duration: {mdd_info['duration_days']} days")
    print(f"Drawdown: {mdd_info['drawdown_pct']:.4%}")
    
    # Top 5 worst drawdowns
    sorted_dd = sorted(drawdowns, key=lambda d: d['drawdown_pct'])
    print(f"\n=== Top 5 Worst Drawdowns ===")
    for i, d in enumerate(sorted_dd[:5], 1):
        print(f"  {i}. {d['drawdown_pct']:.4%} | {d['start_date']} ~ {d['end_date']} | "
              f"Trough: {d['trough_date']} | {d['duration_days']} days | Recovered: {d['recovered']}")
    
    # Yearly analysis
    print("\n=== Yearly Equity ===")
    yearly_equity = compute_yearly_equity(equity_curve)
    for year in sorted(yearly_equity.keys()):
        val = yearly_equity[year]
        if year == min(yearly_equity.keys()):
            prev = initial
        else:
            prev = yearly_equity[str(int(year)-1)]
        ret = (val - prev) / prev
        # Yearly MDD would need per-year equity curve - skip for now
        print(f"  {year}: {val:,.0f} (Return: {ret:.4%})")
    
    # Load KOSPI for comparison
    kospi_annual = load_kospi_data()
    print(f"\nKOSPI Annual Returns: {kospi_annual}")
    
    # Save results
    output = {
        'analysis_date': '2026-08-16',
        'source': 'full_smoke_result.pkl (2,154 trades, post-fix baseline)',
        'overall': {
            'initial_capital': initial,
            'final_equity': final,
            'total_return': total_ret,
            'cagr': cagr_val,
            'max_drawdown': mdd_val,
            'sharpe': sharpe_val,
            'total_trades': len(portfolio.closed_positions)
        },
        'drawdown_analysis': dd_analysis,
        'drawdowns': [
            {
                'start_date': d['start_date'],
                'end_date': d['end_date'],
                'trough_date': d['trough_date'],
                'peak_value': d['peak_value'],
                'trough_value': d['trough_value'],
                'drawdown_pct': d['drawdown_pct'],
                'duration_days': d['duration_days'],
                'recovered': d['recovered']
            }
            for d in sorted_dd
        ],
        'yearly_equity': yearly_equity,
        'kospi_annual': kospi_annual
    }
    
    output_dir = "reports/2026-08-15-trend-breakout-v1-benchmark-analysis"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "long_term_drawdown_analysis.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {output_path}")
    
    return output


if __name__ == "__main__":
    import pickle
    import json
    main()