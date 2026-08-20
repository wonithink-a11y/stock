import json
import sys
from datetime import date as _date

def _to_ordinal(date_str):
    y, m, d = map(int, date_str.split("-"))
    return _date(y, m, d).toordinal()

def realized_pnl_metrics(trades, initial_capital=100000000):
    events = sorted((t['exit_date'], t['pnl']) for t in trades)
    curve = []
    eq = initial_capital
    for d, pnl in events:
        eq += pnl
        curve.append((d, eq))
    if not curve:
        return None
    
    total_ret = (eq - initial_capital) / initial_capital
    
    start_date = _date(2014, 5, 13)
    end_date = _date(2026, 8, 3)
    years = (end_date - start_date).days / 365.25
    cagr_val = (eq / initial_capital) ** (1/years) - 1
    
    peak = curve[0][1]
    max_dd = 0
    for _, v in curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd
    
    import numpy as np
    daily_rets = []
    for i in range(1, len(curve)):
        daily_rets.append((curve[i][1] - curve[i-1][1]) / curve[i-1][1])
    sharpe_val = np.mean(daily_rets) / np.std(daily_rets) * np.sqrt(252) if np.std(daily_rets) > 0 else 0
    
    sortino_denom = np.sqrt(np.mean([min(r, 0)**2 for r in daily_rets])) if daily_rets else 0
    sortino_val = np.mean(daily_rets) / sortino_denom * np.sqrt(252) if sortino_denom > 0 else 0
    
    calmar_val = cagr_val / abs(max_dd) if max_dd != 0 else 0
    
    return {
        "finalEquity": eq,
        "totalReturn": total_ret,
        "cagr": cagr_val,
        "mdd": max_dd,
        "sharpe": sharpe_val,
        "sortino": sortino_val,
        "calmar": calmar_val,
    }

def trade_stats(trades):
    if not trades:
        return {}
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    win_count = len(wins)
    loss_count = len(losses)
    total_count = len(trades)
    win_rate = win_count / total_count if total_count else 0
    avg_win = sum(t['pnl'] for t in wins) / win_count if win_count else 0
    avg_loss = sum(t['pnl'] for t in losses) / loss_count if loss_count else 0
    win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    gross_win = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    profit_factor = gross_win / gross_loss if gross_loss != 0 else 0
    expectancy = sum(t['pnl'] for t in trades) / total_count if total_count else 0
    avg_holding = sum(_to_ordinal(t['exit_date']) - _to_ordinal(t['entry_date']) for t in trades) / total_count if total_count else 0
    
    # Consecutive wins/losses
    max_consec_wins = 0
    max_consec_losses = 0
    curr_wins = 0
    curr_losses = 0
    for t in sorted(trades, key=lambda x: x['exit_date']):
        if t['pnl'] > 0:
            curr_wins += 1
            curr_losses = 0
            max_consec_wins = max(max_consec_wins, curr_wins)
        else:
            curr_losses += 1
            curr_wins = 0
            max_consec_losses = max(max_consec_losses, curr_losses)
    
    return {
        "tradeCount": total_count,
        "winCount": win_count,
        "lossCount": loss_count,
        "winRate": win_rate,
        "avgWin": avg_win,
        "avgLoss": avg_loss,
        "winLossRatio": win_loss_ratio,
        "profitFactor": profit_factor,
        "expectancy": expectancy,
        "avgHoldingPeriod": avg_holding,
        "maxConsecutiveWins": max_consec_wins,
        "maxConsecutiveLosses": max_consec_losses,
    }

# Load run_a1a_only.json
with open('research/strategy-lab/reports/2026-08-17-survivorship-bias-measurement/run_a1a_only.json', 'r') as f:
    a1a_only = json.load(f)

# Load run_merged.json
with open('research/strategy-lab/reports/2026-08-17-survivorship-bias-measurement/run_merged.json', 'r') as f:
    merged = json.load(f)

print("=" * 80)
print("INDEPENDENT VERIFICATION: DeepSeek Survivorship Bias Measurement")
print("=" * 80)
print()

# Verify A1A_ONLY matches original baseline
print("--- A1A_ONLY Verification ---")
a1a_trades = a1a_only['allTrades']
print(f"Trades from JSON: {len(a1a_trades)}")
print(f"Reported closed: {a1a_only['resultTable']['tradeCount']}")

a1a_metrics = realized_pnl_metrics(a1a_trades)
a1a_tstats = trade_stats(a1a_trades)

print()
print("Metrics Comparison:")
print(f"  finalEquity: reported={a1a_only['resultTable']['finalEquity']:.2f}  recalc={a1a_metrics['finalEquity']:.2f}  diff={abs(a1a_only['resultTable']['finalEquity'] - a1a_metrics['finalEquity']):.2f}")
print(f"  totalReturn: reported={a1a_only['resultTable']['totalReturn']:.6f}  recalc={a1a_metrics['totalReturn']:.6f}  diff={abs(a1a_only['resultTable']['totalReturn'] - a1a_metrics['totalReturn']):.6f}")
print(f"  CAGR:        reported={a1a_only['resultTable']['cagr']:.6f}  recalc={a1a_metrics['cagr']:.6f}  diff={abs(a1a_only['resultTable']['cagr'] - a1a_metrics['cagr']):.6f}")
print(f"  MDD:         reported={a1a_only['resultTable']['mdd']:.6f}  recalc={a1a_metrics['mdd']:.6f}  diff={abs(a1a_only['resultTable']['mdd'] - a1a_metrics['mdd']):.6f}")
print(f"  Sharpe:      reported={a1a_only['resultTable']['sharpe']:.6f}  recalc={a1a_metrics['sharpe']:.6f}  diff={abs(a1a_only['resultTable']['sharpe'] - a1a_metrics['sharpe']):.6f}")

print()
print("Trade Stats Comparison:")
for k in ['tradeCount', 'winRate', 'avgWin', 'avgLoss', 'winLossRatio', 'profitFactor', 'expectancy', 'avgHoldingPeriod', 'maxConsecutiveWins', 'maxConsecutiveLosses']:
    r = a1a_only['resultTable'].get(k)
    c = a1a_tstats.get(k)
    print(f"  {k}: reported={r}  recalc={c}")

print()
print(f"Same-bar: reported={a1a_only['sameBarCensus']['sameBarTrades']}  recalc={len([t for t in a1a_trades if t['entry_date'] == t['exit_date']])}")

# Now MERGED
print()
print("=" * 80)
print("--- MERGED Verification ---")
merged_trades = merged['allTrades']
print(f"Trades from JSON: {len(merged_trades)}")
print(f"Reported closed: {merged['resultTable']['tradeCount']}")

merged_metrics = realized_pnl_metrics(merged_trades)
merged_tstats = trade_stats(merged_trades)

print()
print("Metrics Comparison:")
print(f"  finalEquity: reported={merged['resultTable']['finalEquity']:.2f}  recalc={merged_metrics['finalEquity']:.2f}  diff={abs(merged['resultTable']['finalEquity'] - merged_metrics['finalEquity']):.2f}")
print(f"  totalReturn: reported={merged['resultTable']['totalReturn']:.6f}  recalc={merged_metrics['totalReturn']:.6f}  diff={abs(merged['resultTable']['totalReturn'] - merged_metrics['totalReturn']):.6f}")
print(f"  CAGR:        reported={merged['resultTable']['cagr']:.6f}  recalc={merged_metrics['cagr']:.6f}  diff={abs(merged['resultTable']['cagr'] - merged_metrics['cagr']):.6f}")
print(f"  MDD:         reported={merged['resultTable']['mdd']:.6f}  recalc={merged_metrics['mdd']:.6f}  diff={abs(merged['resultTable']['mdd'] - merged_metrics['mdd']):.6f}")
print(f"  Sharpe:      reported={merged['resultTable']['sharpe']:.6f}  recalc={merged_metrics['sharpe']:.6f}  diff={abs(merged['resultTable']['sharpe'] - merged_metrics['sharpe']):.6f}")

print()
print("Trade Stats Comparison:")
for k in ['tradeCount', 'winRate', 'avgWin', 'avgLoss', 'winLossRatio', 'profitFactor', 'expectancy', 'avgHoldingPeriod', 'maxConsecutiveWins', 'maxConsecutiveLosses']:
    r = merged['resultTable'].get(k)
    c = merged_tstats.get(k)
    print(f"  {k}: reported={r}  recalc={c}")

print()
print(f"Same-bar: reported={merged['sameBarCensus']['sameBarTrades']}  recalc={len([t for t in merged_trades if t['entry_date'] == t['exit_date']])}")
print(f"A1b trades: reported={merged['a1bTradeCensus']['a1bTradeCount']}  PnL={merged['a1bTradeCensus']['a1bNetPnl']:.2f}")

# Verify A1b trades
a1b_trades_merged = [t for t in merged_trades if t['symbol'] in [e['ticker'] for e in merged['universe']['entries'] if e['source'] == 'A1B']] if 'universe' in merged else []
# Need to get A1B symbols from universe
with open('research/strategy-lab/run_5dc_v1a_p_merged.py', 'r') as f:
    pass  # We know the A1B symbols from the a1bTradeCensus

# Let's check the a1b_net_pnl by symbol
a1b_pnl_by_sym = {}
for t in merged_trades:
    # We don't have source in trade, but we can check if symbol is A1B
    pass

# Instead, check the A1b PnL from the census
print(f"\nA1b Census: {merged['a1bTradeCensus']['a1bSymbolsWithTrades']} symbols, {merged['a1bTradeCensus']['a1bTradeCount']} trades, net PnL={merged['a1bTradeCensus']['a1bNetPnl']:.2f}")

# Delta calculation
print()
print("=" * 80)
print("--- DELTA (MERGED - A1A_ONLY) ---")
print(f"  ΔCAGR:      {merged_metrics['cagr'] - a1a_metrics['cagr']:.6f} ({merged_metrics['cagr']*100 - a1a_metrics['cagr']*100:.4f}pp)")
print(f"  ΔMDD:       {merged_metrics['mdd'] - a1a_metrics['mdd']:.6f} ({merged_metrics['mdd']*100 - a1a_metrics['mdd']*100:.4f}pp)")
print(f"  ΔfinalEquity: {merged_metrics['finalEquity'] - a1a_metrics['finalEquity']:,.0f}")
print(f"  Δclosed:    {len(merged_trades) - len(a1a_trades)}")
print(f"  ΔwinRate:   {merged_tstats['winRate'] - a1a_tstats['winRate']:.6f}")
print(f"  ΔPF:        {merged_tstats['profitFactor'] - a1a_tstats['profitFactor']:.6f}")

# Compare with DeepSeek reported deltas
print()
print("DeepSeek reported deltas (from comparison.json):")
print(f"  ΔCAGR:      0.016206 (+1.62pp)")
print(f"  ΔMDD:       0.007129 (+0.71pp)")
print(f"  ΔfinalEquity: 6758408.8")
print(f"  Δclosed:    -7")
print(f"  ΔwinRate:   0.002421")

# Verify finalEquity = initial + sum(pnl)
print()
print("=" * 80)
print("--- EQUITY CONSISTENCY CHECK ---")
a1a_sum_pnl = sum(t['pnl'] for t in a1a_trades)
a1a_final_calc = 100000000 + a1a_sum_pnl
print(f"A1A_ONLY: sum(pnl)={a1a_sum_pnl:,.2f}, initial+sum={a1a_final_calc:,.2f}, reported={a1a_only['resultTable']['finalEquity']:.2f}, diff={abs(a1a_final_calc - a1a_only['resultTable']['finalEquity']):.2f}")

merged_sum_pnl = sum(t['pnl'] for t in merged_trades)
merged_final_calc = 100000000 + merged_sum_pnl
print(f"MERGED:   sum(pnl)={merged_sum_pnl:,.2f}, initial+sum={merged_final_calc:,.2f}, reported={merged['resultTable']['finalEquity']:.2f}, diff={abs(merged_final_calc - merged['resultTable']['finalEquity']):.2f}")

# Check A1b trade displacement mechanism
print()
print("=" * 80)
print("--- SLOT COMPETITION ANALYSIS ---")
# Count trades per day for both runs
from collections import defaultdict

def daily_trade_counts(trades):
    by_date = defaultdict(int)
    for t in trades:
        by_date[t['entry_date']] += 1
    return by_date

a1a_daily = daily_trade_counts(a1a_trades)
merged_daily = daily_trade_counts(merged_trades)

# Days where merged has fewer A1A entries
days_with_diff = 0
total_displaced = 0
for date, a1a_count in a1a_daily.items():
    merged_count = merged_daily.get(date, 0)
    if merged_count < a1a_count:
        days_with_diff += 1
        total_displaced += a1a_count - merged_count

print(f"Days with fewer entries in MERGED: {days_with_diff}")
print(f"Total displaced entries: {total_displaced}")

# Check if A1b trades fill some slots
a1b_by_date = defaultdict(int)
a1b_symbols = set()  # Need A1B symbol list
# We can infer from a1bTradeCensus
print(f"A1b trades: {merged['a1bTradeCensus']['a1bTradeCount']} across {merged['a1bTradeCensus']['a1bSymbolsWithTrades']} symbols")

# Compare entry counts
a1a_entries = sum(a1a_daily.values())
merged_entries = sum(merged_daily.values())
print(f"A1A_ONLY total entries: {a1a_entries}")
print(f"MERGED total entries: {merged_entries}")
print(f"Difference: {merged_entries - a1a_entries}")

# DeepSeek claims: 366 A1A trades displaced (-18.1M), 240 new A1A trades (+5.2M), 119 A1b trades (-5.5M) -> net +6.76M
# Let's verify this by looking at which A1A trades are in both vs only in A1A_ONLY

# Create sets of (symbol, entry_date) for comparison
a1a_set = set((t['symbol'], t['entry_date']) for t in a1a_trades)
merged_set = set((t['symbol'], t['entry_date']) for t in merged_trades)

only_in_a1a = a1a_set - merged_set
only_in_merged = merged_set - a1a_set
in_both = a1a_set & merged_set

print(f"\nTrade overlap analysis:")
print(f"  In both: {len(in_both)}")
print(f"  Only in A1A_ONLY: {len(only_in_a1a)}")
print(f"  Only in MERGED: {len(only_in_merged)}")

# PnL of displaced trades
displaced_pnl = sum(t['pnl'] for t in a1a_trades if (t['symbol'], t['entry_date']) in only_in_a1a)
new_pnl = sum(t['pnl'] for t in merged_trades if (t['symbol'], t['entry_date']) in only_in_merged)
print(f"  Displaced PnL (only in A1A): {displaced_pnl:,.0f}")
print(f"  New PnL (only in MERGED): {new_pnl:,.0f}")

# A1b PnL
# We need to identify A1b trades in merged
# Let's load universe to get A1B symbols
import json
with open('data/backfill/universe/a1b/delisted.jsonl', 'r') as f:
    a1b_symbols = set(json.loads(line)['ticker'] for line in f)

a1b_trades_merged = [t for t in merged_trades if t['symbol'] in a1b_symbols]
a1b_pnl_calc = sum(t['pnl'] for t in a1b_trades_merged)
print(f"  A1b trades identified: {len(a1b_trades_merged)}")
print(f"  A1b PnL calculated: {a1b_pnl_calc:,.2f}")
print(f"  Reported A1b PnL: {merged['a1bTradeCensus']['a1bNetPnl']:,.2f}")