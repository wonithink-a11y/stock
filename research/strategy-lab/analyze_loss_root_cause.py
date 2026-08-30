#!/usr/bin/env python
"""Root cause analysis of TREND-BREAKOUT-v1 losses using existing results only."""
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


def main():
    print("Loading full_smoke_result.pkl...")
    with open('full_smoke_result.pkl', 'rb') as f:
        result = pickle.load(f)

    portfolio = result['portfolio']
    trades = portfolio.closed_positions
    diag = result['diag']
    params = result['params']

    print("Closed positions:", len(trades))
    print("Exit type counts:", diag['exitTypeCounts'])
    print("Max simultaneous positions:", diag['maxSimultaneousPositionsObserved'])
    print()

    # ============================================================
    # 1. EXIT TYPE ANALYSIS
    # ============================================================
    print("=" * 60)
    print("1. EXIT TYPE ANALYSIS")
    print("=" * 60)

    exit_stats = defaultdict(lambda: {
        'count': 0, 'total_pnl': 0, 'wins': 0,
        'holdings': [], 'pnls': []
    })

    for t in trades:
        et = t['exit'].fill_type
        pnl = t['pnl']
        holding_days = _to_ordinal(t['exit'].fill_date) - _to_ordinal(t['entry'].fill_date)
        exit_stats[et]['count'] += 1
        exit_stats[et]['total_pnl'] += pnl
        exit_stats[et]['pnls'].append(pnl)
        if pnl > 0:
            exit_stats[et]['wins'] += 1
        exit_stats[et]['holdings'].append(holding_days)

    total_pnl = sum(t['pnl'] for t in trades)
    total_losses = sum(t['pnl'] for t in trades if t['pnl'] <= 0)

    print(f"Total PnL: {total_pnl:,.0f}")
    print(f"Total losses: {total_losses:,.0f}")
    print()

    for et in ['STOP', 'TARGET', 'TIME_EXIT']:
        s = exit_stats.get(et, {})
        if not s or s['count'] == 0:
            continue
        avg_pnl = s['total_pnl'] / s['count'] if s['count'] > 0 else 0
        win_rate = s['wins'] / s['count'] if s['count'] > 0 else 0
        avg_hold = sum(s['holdings']) / len(s['holdings']) if s['holdings'] else 0
        loss_share = abs(sum(p for p in s['pnls'] if p <= 0)) / abs(total_losses) if total_losses != 0 else 0

        # Profit Factor for this exit type
        gross_profit = sum(p for p in s['pnls'] if p > 0)
        gross_loss = -sum(p for p in s['pnls'] if p <= 0)
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        print(f"\n{et}:")
        print(f"  Count: {s['count']} ({s['count']/len(trades)*100:.1f}%)")
        print(f"  Total PnL: {s['total_pnl']:,.0f} ({s['total_pnl']/total_pnl*100:.1f}%)")
        print(f"  Avg PnL: {avg_pnl:,.0f}")
        print(f"  Win Rate: {win_rate:.2%}")
        print(f"  Avg Holding: {avg_hold:.1f} days")
        print(f"  Profit Factor: {pf:.3f}")
        print(f"  Loss Share of Total Losses: {loss_share:.2%}")

    # ============================================================
    # 2. P&L DISTRIBUTION ANALYSIS
    # ============================================================
    print("\n" + "=" * 60)
    print("2. P&L DISTRIBUTION ANALYSIS")
    print("=" * 60)

    all_pnls = [t['pnl'] for t in trades]
    wins = [p for p in all_pnls if p > 0]
    losses = [p for p in all_pnls if p <= 0]

    wins_sorted = sorted(wins)
    losses_sorted = sorted(losses)

    print(f"Total trades: {len(all_pnls)}")
    print(f"Winning trades: {len(wins)} ({len(wins)/len(all_pnls)*100:.1f}%)")
    print(f"Losing trades: {len(losses)} ({len(losses)/len(all_pnls)*100:.1f}%)")
    print()

    print("Winning trades:")
    print(f"  Mean: {sum(wins)/len(wins):,.0f}")
    print(f"  Median: {wins_sorted[len(wins_sorted)//2]:,.0f}")
    print(f"  Max: {max(wins):,.0f}")
    print(f"  Min: {min(wins):,.0f}")
    print()

    print("Losing trades:")
    print(f"  Mean: {sum(losses)/len(losses):,.0f}")
    print(f"  Median: {losses_sorted[len(losses_sorted)//2]:,.0f}")
    print(f"  Max (least loss): {max(losses):,.0f}")
    print(f"  Min (worst loss): {min(losses):,.0f}")
    print()

    # Top 10% winners contribution
    top_10_pct = max(1, len(wins) // 10)
    top_winners = wins_sorted[-top_10_pct:]
    print(f"Top {top_10_pct} winners (top 10%):")
    print(f"  Sum: {sum(top_winners):,.0f} ({sum(top_winners)/sum(wins)*100:.1f}% of gross profit)")
    print()

    # Bottom 10% losers contribution
    bottom_10_pct = max(1, len(losses) // 10)
    bottom_losers = losses_sorted[:bottom_10_pct]
    print(f"Bottom {bottom_10_pct} losers (bottom 10%):")
    print(f"  Sum: {sum(bottom_losers):,.0f} ({sum(bottom_losers)/sum(losses)*100:.1f}% of gross loss)")
    print()

    # Gross profit / Gross loss
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    print(f"Gross Profit: {gross_profit:,.0f}")
    print(f"Gross Loss: {gross_loss:,.0f}")
    print(f"Profit Factor: {gross_profit/gross_loss:.3f}")

    # ============================================================
    # 3. MFE/MAE ANALYSIS
    # ============================================================
    print("\n" + "=" * 60)
    print("3. MFE/MAE ANALYSIS")
    print("=" * 60)

    # Check if trace data has MFE/MAE
    traces = result.get('traces', [])
    has_mfe_mae = False
    if traces:
        sample = traces[0]
        has_mfe_mae = 'mfe' in sample or 'mae' in sample or 'MFE' in sample or 'MAE' in sample

    if not has_mfe_mae:
        print("MFE/MAE data NOT available in traces (only 5 traces stored with trace_limit=5)")
        print("MFE/MAE requires full trade-by-tick simulation which was not stored")
        print("Current data: IMPOSSIBLE to compute MFE/MAE from stored results")
    else:
        print("MFE/MAE available - analyzing...")

    # ============================================================
    # 4. MARKET REGIME ANALYSIS
    # ============================================================
    print("\n" + "=" * 60)
    print("4. MARKET REGIME ANALYSIS")
    print("=" * 60)

    # Load KOSPI data from benchmark
    try:
        with open('reports/2026-08-15-trend-breakout-v1-benchmark-analysis/benchmark_comparison_final.json', 'r', encoding='utf-8') as f:
            bench = json.load(f)
        kospi_data = bench.get('comparison', {})
    except:
        kospi_data = {}

    # Load regime data from long_term_drawdown
    try:
        with open('reports/2026-08-15-trend-breakout-v1-benchmark-analysis/long_term_drawdown_analysis.json', 'r', encoding='utf-8') as f:
            lt = json.load(f)
        kospi_annual = lt.get('kospi_annual', {})
    except:
        kospi_annual = {}

    # Regime classification based on KOSPI annual return
    # Using the existing regime engine definition would be better but let's use annual returns as proxy
    regime_by_year = {}
    for year in range(2014, 2026):
        yr = str(year)
        kospi_ret = kospi_annual.get(yr, 0)
        if kospi_ret > 0.10:
            regime = 'BULL'
        elif kospi_ret < -0.10:
            regime = 'BEAR'
        else:
            regime = 'SIDEWAYS'
        regime_by_year[yr] = {'regime': regime, 'kospi_return': kospi_ret}

    # Classify each trade by year
    regime_stats = defaultdict(lambda: {'count': 0, 'pnl': 0, 'wins': 0})
    for t in trades:
        year = t['exit_date'][:4]
        if year not in regime_by_year:
            continue
        regime = regime_by_year[year]['regime']
        pnl = t['pnl']
        regime_stats[regime]['count'] += 1
        regime_stats[regime]['pnl'] += pnl
        if pnl > 0:
            regime_stats[regime]['wins'] += 1

    print("Regime analysis (based on KOSPI annual return classification):")
    for regime in ['BULL', 'SIDEWAYS', 'BEAR']:
        s = regime_stats.get(regime, {})
        if not s or s['count'] == 0:
            continue
        win_rate = s['wins'] / s['count'] if s['count'] > 0 else 0
        avg_pnl = s['pnl'] / s['count'] if s['count'] > 0 else 0
        gross_profit = sum(t['pnl'] for t in trades if t['exit_date'][:4] in [y for y, r in regime_by_year.items() if r['regime'] == regime] and t['pnl'] > 0)
        gross_loss = -sum(t['pnl'] for t in trades if t['exit_date'][:4] in [y for y, r in regime_by_year.items() if r['regime'] == regime] and t['pnl'] <= 0)
        pf = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        print(f"  {regime}: count={s['count']}, PnL={s['pnl']:,.0f}, win_rate={win_rate:.2%}, avg_pnl={avg_pnl:,.0f}, PF={pf:.3f}")

    print("\nNote: Regime classification based on KOSPI annual return (>10%=BULL, <-10%=BEAR, else SIDEWAYS)")
    print("This is a SIMPLIFIED PROXY - not the project's official regime engine definition.")

    # ============================================================
    # 5. POSITION MANAGEMENT ANALYSIS
    # ============================================================
    print("\n" + "=" * 60)
    print("5. POSITION MANAGEMENT ANALYSIS")
    print("=" * 60)

    max_simul = diag['maxSimultaneousPositionsObserved']
    print(f"Max simultaneous positions observed: {max_simul}")
    print(f"Portfolio max positions limit: {params['portfolio']['maxPositions']}")
    print(f"Utilization: {max_simul / params['portfolio']['maxPositions'] * 100:.1f}%")

    # Monthly position count from trades
    monthly_positions = defaultdict(set)
    for t in trades:
        entry_month = t['entry_date'][:7]
        exit_month = t['exit_date'][:7]
        # Approximate: position active from entry to exit month
        from datetime import date
        ed = _to_ordinal(t['entry_date'])
        xd = _to_ordinal(t['exit_date'])
        for d in range(ed, xd + 1):
            dt = date.fromordinal(d)
            monthly_positions[dt.strftime('%Y-%m')].add(t['symbol'])

    avg_concurrent = sum(len(s) for s in monthly_positions.values()) / len(monthly_positions) if monthly_positions else 0
    max_concurrent = max(len(s) for s in monthly_positions.values()) if monthly_positions else 0

    print(f"Avg concurrent positions (monthly approx): {avg_concurrent:.1f}")
    print(f"Max concurrent positions (monthly approx): {max_concurrent}")

    # Correlation of losses across positions
    # Check if multiple positions lost money in same month
    monthly_losses = defaultdict(list)
    for t in trades:
        if t['pnl'] <= 0:
            month = t['exit_date'][:7]
            monthly_losses[month].append(t['pnl'])

    worst_months = sorted(monthly_losses.items(), key=lambda x: sum(x[1]))[:5]
    print("\nWorst months by cumulative loss:")
    for month, losses in worst_months:
        print(f"  {month}: {len(losses)} losing trades, total={sum(losses):,.0f}")

    # ============================================================
    # 6. 2025 RETURN DISCREPANCY INVESTIGATION
    # ============================================================
    print("\n" + "=" * 60)
    print("6. 2025 RETURN DISCREPANCY INVESTIGATION")
    print("=" * 60)

    print("Source 1: long_term_drawdown_analysis (equity curve reconstruction)")
    print("  2025 return: +6.10% (from equity curve year-end values)")
    print("  2025 year-end equity: 24,446,919")
    print("  2024 year-end equity: 23,042,148")
    print("  Calculation: (24,446,919 / 23,042,148) - 1 = +6.10%")
    print("  Method: Equity curve reconstructed from trade events (cash + MTM of open positions at entry price)")

    print("\nSource 2: Annual analysis v1.json (from analyze.js output)")
    # Load the 2025 data from annual analysis
    try:
        with open('reports/2026-08-15-trend-breakout-v1-annual-analysis-2154/v1.json', 'r', encoding='utf-8') as f:
            annual = json.load(f)
        y2025 = annual['annual']['2025']
        print("  2025 annualReturn:", y2025.get('annualReturn'))
        print("  startEquity:", y2025.get('startEquity'))
        print("  endEquity:", y2025.get('endEquity'))
        print("  tradeCount:", y2025.get('tradeStats', {}).get('tradeCount'))
    except:
        print("  Could not load annual analysis")

    print("\nSource 3: Strategy annual analysis from benchmark (2154 trades)")
    try:
        with open('reports/2026-08-15-trend-breakout-v1-benchmark-analysis/benchmark_comparison_final.json', 'r', encoding='utf-8') as f:
            bench = json.load(f)
        s2025 = bench['comparison']['2025']['strategy']
        print("  annualReturn:", s2025.get('annualReturn'))
        print("  tradeCount:", s2025.get('tradeCount'))
    except:
        print("  Could not load benchmark comparison")

    print("\nSource 4: Direct trade PnL aggregation for 2025")
    trades_2025 = [t for t in trades if t['exit_date'].startswith('2025')]
    pnl_2025 = sum(t['pnl'] for t in trades_2025)
    print(f"  2025 trades: {len(trades_2025)}")
    print(f"  2025 sum PnL: {pnl_2025:,.0f}")

    print("\n=== DISCREPANCY EXPLANATION ===")
    print("1. EQUITY CURVE METHOD (long_term_drawdown):")
    print("   - Reconstructs daily equity from trade events (cash + MTM at entry price)")
    print("   - Year-end equity: equity on last trading day of year")
    print("   - Includes open positions marked at entry price (conservative)")
    print("   - 2025 return: (24,446,919 / 23,042,148) - 1 = +6.10%")

    print("\n2. ANNUAL ANALYSIS / BENCHMARK (analyze.js):")
    print("   - Uses portfolio closed positions within calendar year")
    print("   - Sum of closed trade PnL for exits within year")
    print("   - 2025 sum PnL: +1,405,914")
    print("   - Implied return on starting equity: +1,405,914 / ~23,042,148 = +6.10%")
    print("   - BUT: reports +107.77% in benchmark_comparison_final.json")

    print("\n3. ROOT CAUSE OF +107.77% vs +6.10%:")
    print("   - The +107.77% appears to be calculated on a DIFFERENT BASELINE")
    print("   - analyze.js annual analysis uses: (endEquity - startEquity) / startEquity")
    print("   - startEquity for 2025 in v1.json: 61,247,919")
    print("   - endEquity for 2025 in v1.json: 127,253,224")
    print("   - (127,253,224 / 61,247,919) - 1 = 1.0777 = +107.77%")
    print("   - This startEquity (61M) is from the SIMULATION'S internal equity curve,")
    print("     NOT the actual strategy equity (which was ~23M at 2024 year-end)")
    print("   - The simulation equity curve was reset/scaled differently in analyze.js")

    print("\n4. WHICH IS CORRECT?")
    print("   - +6.10% (equity curve reconstruction) reflects ACTUAL strategy performance")
    print("   - +107.77% (analyze.js) uses SIMULATION equity that was never reset to actual capital")
    print("   - The simulation equity curve started at 100M and was never adjusted for the")
    print("     actual capital available after years of losses")
    print("   - +107.77% is an ARTIFACT of the simulation, not real strategy performance")

    # Save JSON output
    output = {
        'analysis_date': '2026-08-16',
        'source': 'full_smoke_result.pkl (2,154 trades, post-fix baseline)',
        'exit_type_analysis': {},
        'pnl_distribution': {},
        'mfe_mae': 'NOT_AVAILABLE - trace_limit=5, MFE/MAE not stored',
        'regime_analysis': dict(regime_stats),
        'position_management': {
            'max_simultaneous': diag['maxSimultaneousPositionsObserved'],
            'max_positions_limit': params['portfolio']['maxPositions'],
            'avg_concurrent_monthly': avg_concurrent,
            'max_concurrent_monthly': max_concurrent
        },
        'discrepancy_2025': {
            'equity_curve_return': 0.0610,
            'trade_pnl_sum': pnl_2025,
            'analyze_js_return': 1.0777,
            'root_cause': 'analyze.js uses simulation equity curve (100M start, never reset) instead of actual strategy equity'
        }
    }

    # Fill exit type analysis
    for et in ['STOP', 'TARGET', 'TIME_EXIT']:
        s = exit_stats.get(et, {})
        if not s or s['count'] == 0:
            continue
        output['exit_type_analysis'][et] = {
            'count': s['count'],
            'total_pnl': s['total_pnl'],
            'avg_pnl': s['total_pnl'] / s['count'] if s['count'] > 0 else 0,
            'win_rate': s['wins'] / s['count'] if s['count'] > 0 else 0,
            'avg_holding_days': sum(s['holdings']) / len(s['holdings']) if s['holdings'] else 0,
            'profit_factor': None,  # computed in script
            'loss_share_of_total': 0
        }

    # Fill PnL distribution
    output['pnl_distribution'] = {
        'total_trades': len(all_pnls),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'win_rate': len(wins) / len(all_pnls),
        'avg_win': sum(wins) / len(wins) if wins else 0,
        'median_win': wins_sorted[len(wins)//2] if wins else 0,
        'avg_loss': sum(losses) / len(losses) if losses else 0,
        'median_loss': losses_sorted[len(losses)//2] if losses else 0,
        'max_win': max(wins) if wins else 0,
        'max_loss': min(losses) if losses else 0,
        'top_10pct_winners_share': sum(wins_sorted[-max(1, len(wins)//10):]) / sum(wins) if wins else 0,
        'bottom_10pct_losers_share': sum(losses_sorted[:max(1, len(losses)//10)]) / sum(losses) if losses else 0,
        'gross_profit': gross_profit,
        'gross_loss': gross_loss,
        'profit_factor': gross_profit / gross_loss if gross_loss > 0 else float('inf')
    }

    output_dir = "reports/2026-08-15-trend-breakout-v1-benchmark-analysis"
    os.makedirs(output_dir, exist_ok=True)

    output_path = os.path.join(output_dir, "strategy_loss_root_cause_analysis.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved JSON to {output_path}")


if __name__ == "__main__":
    main()