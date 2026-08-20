import sys
sys.path.insert(0, 'research/strategy-lab')
import pickle
import pandas as pd
import json

with open('research/strategy-lab/5dc_v1a_p_resolved.pkl', 'rb') as f:
    data = pickle.load(f)

portfolio = data['portfolio']
resolved = data['resolved']

# Build a lookup: (symbol, entry_date, exit_date) -> risk_spec
risk_lookup = {}
for item in resolved:
    sig, order, entry_fill, exit_fill, risk_spec, atr_t = item
    key = (order.symbol, entry_fill.fill_date, exit_fill.fill_date)
    risk_lookup[key] = risk_spec

# Extract same-bar STOP trades
same_bar_stops = []
for p in portfolio.closed_positions:
    entry = p['entry']
    exit_ = p['exit']
    if p['entry_date'] == exit_.fill_date and exit_.fill_type == 'STOP':
        key = (p['symbol'], p['entry_date'], exit_.fill_date)
        risk_spec = risk_lookup.get(key)
        stop_distance = risk_spec.stop_distance if risk_spec else None
        stop_price = entry.fill_price - stop_distance if stop_distance else None
        same_bar_stops.append({
            'symbol': p['symbol'],
            'date': p['entry_date'],
            'entry_price': entry.fill_price,
            'exit_price': exit_.fill_price,
            'stop_price': stop_price,
            'stop_distance': stop_distance,
            'atr_at_signal': risk_spec.stop_distance / 2.0 if risk_spec and risk_spec.stop_distance else None,
            'shares': p['shares'],
            'pnl': p['pnl'],
        })

print(f"Total same-bar STOP trades: {len(same_bar_stops)}")
print()

# Save for later use
with open('same_bar_stops.json', 'w') as f:
    json.dump(same_bar_stops, f, indent=2, default=str)

# Print all
for i, t in enumerate(same_bar_stops):
    print(f"  {i+1}. {t['symbol']} {t['date']} entry={t['entry_price']:.2f} stop={t['stop_price']:.2f} exit={t['exit_price']:.2f} atr={t['atr_at_signal']:.2f} pnl={t['pnl']:.0f}")

print()
print("All symbols:", sorted(set(t['symbol'] for t in same_bar_stops)))
print("Date range:", min(t['date'] for t in same_bar_stops), "~", max(t['date'] for t in same_bar_stops))