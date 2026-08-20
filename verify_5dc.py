import sys
sys.path.insert(0, 'research/strategy-lab')
import pickle

with open('research/strategy-lab/5dc_v1a_p_resolved.pkl', 'rb') as f:
    data = pickle.load(f)

portfolio = data['portfolio']
diag = data['diag']
params = data['params']

print('=== Independent Verification of 5DC-v1A-P Post-Fix (same-bar fix applied) ===')
print()
print('Run Identification:')
print('  strategyId: 5dc_v1a_p')
print('  runClass:', diag["runClass"])
print('  universeMode:', diag["universeMode"])
print('  tickersScanned:', diag["tickersScanned"])
print('  signalCount:', diag["signalCount"])
print('  executableTradeCount:', diag["executableTradeCount"])
print('  portfolioEligibleTradeCount:', diag["portfolioEligibleTradeCount"])
print('  closedPositionCount:', diag["closedPositionCount"])
print('  openPositionCountAtEnd:', diag["openPositionCountAtEnd"])
print('  maxSimultaneousPositionsObserved:', diag["maxSimultaneousPositionsObserved"])
print('  finalCash:', f'{diag["finalCash"]:.2f}')
print('  exitTypeCounts:', diag["exitTypeCounts"])
print()

# Analyze all trades
trades = []
for p in portfolio.closed_positions:
    entry = p['entry']
    exit_ = p['exit']
    from datetime import date as _date
    def _to_ordinal(date_str):
        y, m, d = map(int, date_str.split('-'))
        return _date(y, m, d).toordinal()
    holding = _to_ordinal(exit_.fill_date) - _to_ordinal(p['entry_date'])
    trades.append({
        'pnl': p['pnl'],
        'holding_sessions': holding,
        'symbol': p['symbol'],
        'entry_date': p['entry_date'],
        'exit_date': exit_.fill_date,
        'exit_type': exit_.fill_type,
        'entry_price': entry.fill_price,
        'exit_price': exit_.fill_price,
        'shares': p['shares'],
    })

print('Total closed trades:', len(trades))
print()

# Same-bar census
same_bar = [t for t in trades if t['entry_date'] == t['exit_date']]
from collections import Counter
same_bar_by_type = Counter(t['exit_type'] for t in same_bar)
print('Same-bar trades:', len(same_bar), f'({len(same_bar)/len(trades)*100:.2f}%)')
print('  by exit_type:', dict(same_bar_by_type))
print()

# PnL verification
total_pnl = sum(t['pnl'] for t in trades)
wins = [t for t in trades if t['pnl'] > 0]
losses = [t for t in trades if t['pnl'] <= 0]
print('Total PnL:', f'{total_pnl:,.2f}')
print('Wins:', len(wins), 'Losses:', len(losses))
print('Win rate:', f'{len(wins)/len(trades)*100:.2f}%')
print('Avg win:', f'{sum(t["pnl"] for t in wins)/len(wins):,.2f}')
print('Avg loss:', f'{sum(t["pnl"] for t in losses)/len(losses):,.2f}')
print('Win/Loss ratio:', f'{abs(sum(t["pnl"] for t in wins)/len(wins)) / abs(sum(t["pnl"] for t in losses)/len(losses)):.4f}')
print('Profit factor:', f'{sum(t["pnl"] for t in wins) / abs(sum(t["pnl"] for t in losses)):.4f}')
print('Expectancy:', f'{total_pnl/len(trades):,.2f}')
print('Avg holding:', f'{sum(t["holding_sessions"] for t in trades)/len(trades):.2f} sessions')
print()

# Equity curve (realized PnL at exit events)
events = sorted((t['exit_date'], t['pnl']) for t in trades)
eq = params['portfolio']['initialCapital']
curve = []
for d, pnl in events:
    eq += pnl
    curve.append((d, eq))

print('Initial capital:', f'{params["portfolio"]["initialCapital"]:,.0f}')
print('Final equity:', f'{eq:,.2f}')
print('Total return:', f'{(eq - params["portfolio"]["initialCapital"]) / params["portfolio"]["initialCapital"] * 100:.4f}%')

# CAGR
from datetime import date as _date
start_date = _date(2014, 5, 13)
end_date = _date(2026, 8, 3)
years = (end_date - start_date).days / 365.25
cagr = (eq / params['portfolio']['initialCapital']) ** (1/years) - 1
print('CAGR:', f'{cagr*100:.4f}%')

# MDD
peak = curve[0][1]
max_dd = 0
for _, v in curve:
    if v > peak:
        peak = v
    dd = (v - peak) / peak
    if dd < max_dd:
        max_dd = dd
print('MDD:', f'{max_dd*100:.4f}%')

# Sharpe (daily returns from exit events)
import numpy as np
daily_rets = []
for i in range(1, len(curve)):
    daily_rets.append((curve[i][1] - curve[i-1][1]) / curve[i-1][1])
if daily_rets:
    sharpe = np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(252) if np.std(daily_rets) > 0 else 0
    print('Sharpe:', f'{sharpe:.4f}')

# Check same-bar PnL impact
same_bar_pnl = sum(t['pnl'] for t in same_bar)
print()
print('Same-bar trades PnL:', f'{same_bar_pnl:,.2f}')
print('Same-bar share of total PnL:', f'{same_bar_pnl/total_pnl*100:.2f}%')

# Verify no trade anomalies
print()
print('=== Anomaly Checks ===')
# Check for negative shares
neg_shares = [t for t in trades if t['shares'] <= 0]
print('Negative/zero shares:', len(neg_shares))
# Check for negative prices
neg_prices = [t for t in trades if t['entry_price'] <= 0 or t['exit_price'] <= 0]
print('Non-positive prices:', len(neg_prices))
# Check for holding < 0
neg_holding = [t for t in trades if t['holding_sessions'] < 0]
print('Negative holding:', len(neg_holding))
# Check for zero holding (same-bar)
zero_holding = [t for t in trades if t['holding_sessions'] == 0]
print('Zero holding (same-bar):', len(zero_holding))
# Check PnL formula
pnl_errors = 0
for t in trades:
    gross = (t['exit_price'] - t['entry_price']) * t['shares']
    entry_cost = t['entry_price'] * t['shares'] * params['cost']['entryCostBps'] / 10000
    exit_cost = t['exit_price'] * t['shares'] * params['cost']['exitCostBps'] / 10000
    expected = gross - entry_cost - exit_cost
    if abs(t['pnl'] - expected) > 0.01:
        pnl_errors += 1
print('PnL formula mismatches:', pnl_errors)
print()
print('=== VERIFICATION COMPLETE ===')