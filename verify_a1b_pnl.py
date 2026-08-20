import json

# Get A1B symbols from universe (using the same method as the driver)
with open('data/backfill/universe/a1b/delisted.jsonl', 'r', encoding='utf-8') as f:
    a1b_symbols = set(json.loads(line)['ticker'] for line in f)

print(f"A1B symbols total: {len(a1b_symbols)}")

# Load merged trades
with open('research/strategy-lab/reports/2026-08-17-survivorship-bias-measurement/run_merged.json', 'r') as f:
    merged = json.load(f)

merged_trades = merged['allTrades']

# Identify A1b trades
a1b_trades = [t for t in merged_trades if t['symbol'] in a1b_symbols]
a1a_trades_in_merged = [t for t in merged_trades if t['symbol'] not in a1b_symbols]

print(f"A1b trades in merged: {len(a1b_trades)}")
print(f"A1a trades in merged: {len(a1a_trades_in_merged)}")
print(f"A1b net PnL: {sum(t['pnl'] for t in a1b_trades):,.2f}")
print(f"Reported A1b net PnL: {merged['a1bTradeCensus']['a1bNetPnl']:,.2f}")

# Exit types
from collections import Counter
a1b_exit_types = Counter(t['exit_type'] for t in a1b_trades)
print(f"A1b exit types: {dict(a1b_exit_types)}")

# PnL by exit type
for et in ['STOP', 'TARGET', 'TIME_EXIT']:
    et_trades = [t for t in a1b_trades if t['exit_type'] == et]
    if et_trades:
        pnl = sum(t['pnl'] for t in et_trades)
        print(f"  {et}: {len(et_trades)} trades, PnL={pnl:,.2f}")

# Verify displaced trades PnL breakdown
with open('research/strategy-lab/reports/2026-08-17-survivorship-bias-measurement/run_a1a_only.json', 'r') as f:
    a1a_only = json.load(f)

a1a_trades = a1a_only['allTrades']

a1a_set = set((t['symbol'], t['entry_date']) for t in a1a_trades)
merged_set = set((t['symbol'], t['entry_date']) for t in merged_trades)

only_in_a1a = a1a_set - merged_set
only_in_merged = merged_set - a1a_set
in_both = a1a_set & merged_set

print(f"\nTrade overlap:")
print(f"  In both: {len(in_both)}")
print(f"  Only in A1A_ONLY: {len(only_in_a1a)}")
print(f"  Only in MERGED: {len(only_in_merged)}")

displaced_pnl = sum(t['pnl'] for t in a1a_trades if (t['symbol'], t['entry_date']) in only_in_a1a)
new_pnl = sum(t['pnl'] for t in merged_trades if (t['symbol'], t['entry_date']) in only_in_merged)

print(f"\nDisplaced PnL (only in A1A): {displaced_pnl:,.0f}")
print(f"New PnL (only in MERGED): {new_pnl:,.0f}")

# Break down displaced by A1a vs A1b
displaced_a1b = [t for t in a1a_trades if (t['symbol'], t['entry_date']) in only_in_a1a and t['symbol'] in a1b_symbols]
displaced_a1a = [t for t in a1a_trades if (t['symbol'], t['entry_date']) in only_in_a1a and t['symbol'] not in a1b_symbols]
print(f"\nDisplaced A1b trades: {len(displaced_a1b)} (PnL: {sum(t['pnl'] for t in displaced_a1b):,.0f})")
print(f"Displaced A1a trades: {len(displaced_a1a)} (PnL: {sum(t['pnl'] for t in displaced_a1a):,.0f})")

# New trades breakdown
new_a1b = [t for t in merged_trades if (t['symbol'], t['entry_date']) in only_in_merged and t['symbol'] in a1b_symbols]
new_a1a = [t for t in merged_trades if (t['symbol'], t['entry_date']) in only_in_merged and t['symbol'] not in a1b_symbols]
print(f"\nNew A1b trades: {len(new_a1b)} (PnL: {sum(t['pnl'] for t in new_a1b):,.0f})")
print(f"New A1a trades: {len(new_a1a)} (PnL: {sum(t['pnl'] for t in new_a1a):,.0f})")

# Verify the mechanism: displaced trades net PnL vs new trades net PnL
print(f"\nMechanism check:")
print(f"  Displaced (A1A_ONLY only): {len(only_in_a1a)} trades, PnL={displaced_pnl:,.0f}")
print(f"  New (MERGED only): {len(only_in_merged)} trades, PnL={new_pnl:,.0f}")
print(f"  A1b in MERGED: {len(a1b_trades)} trades, PnL={sum(t['pnl'] for t in a1b_trades):,.0f}")
print(f"  Net effect: {displaced_pnl + new_pnl + sum(t['pnl'] for t in a1b_trades):,.0f} (should equal delta in finalEquity: +6,758,409)")

# Total PnL difference
a1a_total_pnl = sum(t['pnl'] for t in a1a_trades)
merged_total_pnl = sum(t['pnl'] for t in merged_trades)
print(f"\nTotal PnL A1A_ONLY: {a1a_total_pnl:,.0f}")
print(f"Total PnL MERGED: {merged_total_pnl:,.0f}")
print(f"Delta: {merged_total_pnl - a1a_total_pnl:,.0f}")
print(f"Expected delta (finalEquity): +6,758,409")

# Check if the 366 displaced trades include the 119 A1b trades
# DeepSeek claims: 366 A1A displaced (-18.1M), 240 new A1A (+5.2M), 119 A1b (-5.5M)
# My calc: 366 displaced, 359 new, 119 A1b
# Let me check the displaced trades more carefully

print("\n=== DEEPSEEK CLAIM VERIFICATION ===")
print("DeepSeek: 'A1A_ONLY에서 체결됐던 A1A 거래 366건이 슬롯 경쟁으로 밀려난다'")
print(f"My count: Only in A1A_ONLY = {len(only_in_a1a)} (matches 366)")

print("DeepSeek: '이 366건은 net -18.1M'")
print(f"My calc: Displaced PnL = {displaced_pnl:,.0f} (matches -18.1M)")

print("DeepSeek: '대신 240건의 새 A1A 거래(+5.2M)와 A1b 119건(-5.5M)이 편입'")
print(f"My calc: Only in MERGED = {len(only_in_merged)} (359, not 240)")
print(f"         New A1A trades = {len(new_a1a)} (PnL: {sum(t['pnl'] for t in new_a1a):,.0f})")
print(f"         New A1b trades = {len(new_a1b)} (PnL: {sum(t['pnl'] for t in new_a1b):,.0f})")
print(f"         A1b total in MERGED = {len(a1b_trades)} (PnL: {sum(t['pnl'] for t in a1b_trades):,.0f})")

# The difference: DeepSeek might be counting differently
# "240 new A1A trades" might be trades that replaced the displaced ones specifically
# Let me check: of the 359 new trades, how many are A1A vs A1b
print(f"\nNew trades breakdown:")
print(f"  Total new: {len(only_in_merged)}")
print(f"  A1A new: {len(new_a1a)}")
print(f"  A1b new: {len(new_a1b)}")

# The "replaced" trades might be a subset
# Let's see: 366 displaced, 359 new total (240 A1A + 119 A1b = 359)
# DeepSeek says 240 new A1A + 119 A1b = 359 total new
# My calc: 359 new total = 240 A1A + 119 A1b (matches!)
# So new_a1a should be 240, new_a1b should be 119

# Wait, my count shows 359 new total, but split differently
# Let me recount
print(f"\nDetailed new trade count:")
print(f"  len(new_a1a) = {len(new_a1a)}")
print(f"  len(new_a1b) = {len(new_a1b)}")
print(f"  sum = {len(new_a1a) + len(new_a1b)}")
print(f"  len(only_in_merged) = {len(only_in_merged)}")

# They should match
if len(new_a1a) + len(new_a1b) != len(only_in_merged):
    print("MISMATCH!")
else:
    print("MATCH")

# So DeepSeek's numbers: 240 new A1A, 119 A1b = 359 total new
# My numbers should match this
print(f"\nDeepSeek claims: 240 new A1A, 119 A1b")
print(f" My calc: {len(new_a1a)} new A1A, {len(new_a1b)} A1b")

# PnL check
print(f"\nDeepSeek: new A1A +5.2M, A1b -5.5M")
print(f" My calc: new A1A {sum(t['pnl'] for t in new_a1a):,.0f}, new A1b {sum(t['pnl'] for t in new_a1b):,.0f}")
print(f" My calc: A1b total in MERGED {sum(t['pnl'] for t in a1b_trades):,.0f}")