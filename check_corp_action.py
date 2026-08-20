import sys
sys.path.insert(0, 'research/strategy-lab')
from engine.data.a2aProvider import A2aProvider
from pathlib import Path
import json

# Load same-bar stops
with open('same_bar_stops.json', 'r') as f:
    same_bar_stops = json.load(f)

# Group by ticker
by_ticker = {}
for t in same_bar_stops:
    by_ticker.setdefault(t['symbol'], []).append(t)

tickers = list(by_ticker.keys())
print(f"Loading A2a data for {len(tickers)} tickers...")

# Use A2aProvider to load efficiently
provider = A2aProvider(repo_root=".", use_cache=True)
# Load all tickers for full date range to get context
bars_by_ticker = provider.load(tickers, "2014-05-13", "2026-08-03")

print(f"Loaded {len(bars_by_ticker)} tickers")
print()

# Check each same-bar STOP
corp_action_candidates = []
direct_overlap = []

for t in same_bar_stops:
    ticker = t['symbol']
    date = t['date']
    
    if ticker not in bars_by_ticker:
        print(f"  {ticker}: NO DATA IN A2A")
        continue
    
    df = bars_by_ticker[ticker]
    if date not in df.index:
        print(f"  {ticker} {date}: DATE NOT IN BARS")
        continue
    
    row = df.loc[date]
    idx = df.index.get_loc(date)
    
    # Get previous day
    if idx > 0:
        prev_row = df.iloc[idx - 1]
        prev_date = df.index[idx - 1].strftime('%Y-%m-%d')
        prev_close = prev_row['close']
    else:
        prev_row = None
        prev_date = None
        prev_close = None
    
    curr_open = row['open']
    curr_high = row['high']
    curr_low = row['low']
    curr_close = row['close']
    curr_vol = row['volume']
    
    # Calculate gaps
    gap_open_to_prev_close = None
    gap_close_to_prev_close = None
    if prev_close and prev_close > 0:
        gap_open_to_prev_close = (curr_open - prev_close) / prev_close
        gap_close_to_prev_close = (curr_close - prev_close) / prev_close
    
    # Check for corporate action patterns
    # 1. Large overnight gap (>20% or <-20%)
    # 2. Extreme intraday range with low volume
    # 3. Open=High=Low=Close but far from prev_close
    
    is_suspicious = False
    reasons = []
    
    if gap_open_to_prev_close is not None:
        if abs(gap_open_to_prev_close) > 0.20:
            is_suspicious = True
            reasons.append(f"LARGE_GAP_OPEN_{gap_open_to_prev_close:.2%}")
        if abs(gap_close_to_prev_close) > 0.20:
            is_suspicious = True
            reasons.append(f"LARGE_GAP_CLOSE_{gap_close_to_prev_close:.2%}")
    
    # Check intraday range vs prev_close
    if prev_close and prev_close > 0:
        intraday_range = (curr_high - curr_low) / prev_close
        if intraday_range > 0.50:
            is_suspicious = True
            reasons.append(f"WIDE_RANGE_{intraday_range:.2%}")
    
    # Check if excluded
    is_excluded = False  # Will check quality-excluded separately
    
    result = {
        'ticker': ticker,
        'date': date,
        'prev_date': prev_date,
        'prev_close': prev_close,
        'open': curr_open,
        'high': curr_high,
        'low': curr_low,
        'close': curr_close,
        'volume': int(curr_vol),
        'gap_open_pct': gap_open_to_prev_close,
        'gap_close_pct': gap_close_to_prev_close,
        'is_suspicious': is_suspicious,
        'reasons': reasons,
        'entry_price': t['entry_price'],
        'exit_price': t['exit_price'],
        'stop_price': t['stop_price'],
        'atr_at_signal': t['atr_at_signal'],
        'pnl': t['pnl'],
    }
    
    if is_suspicious:
        corp_action_candidates.append(result)
        # Check if the STOP was hit due to the gap
        if t['stop_price'] and curr_low <= t['stop_price']:
            if gap_open_to_prev_close is not None and gap_open_to_prev_close < -0.15:
                # Gap down opened below stop
                direct_overlap.append(result)
            elif curr_low <= t['stop_price'] and curr_low < curr_open:
                # Intraday drop hit stop
                direct_overlap.append(result)

# Load quality-excluded
excluded_path = Path("data/backfill/price/a2a/price-quality-excluded.jsonl.gz")
import gzip
excluded_by_ticker_date = {}
with gzip.open(excluded_path, 'rt', encoding='utf-8') as f:
    for line in f:
        row = json.loads(line)
        key = (row['ticker'], row['violations'][0]['date'] if row['violations'] else '')
        excluded_by_ticker_date.setdefault(row['ticker'], []).append(row)

# Mark excluded
for r in corp_action_candidates:
    ticker = r['ticker']
    date = r['date']
    if ticker in excluded_by_ticker_date:
        for ex in excluded_by_ticker_date[ticker]:
            for v in ex['violations']:
                if v['date'] == date:
                    r['quality_excluded'] = True
                    r['exclusion_reason'] = ex['reason']
                    break

# Print results
print(f"\n=== CORPORATE ACTION CANDIDATES: {len(corp_action_candidates)} / {len(same_bar_stops)} ===\n")

for r in corp_action_candidates:
    excl = " [QUALITY-EXCLUDED]" if r.get('quality_excluded') else ""
    print(f"  {r['ticker']} {r['date']}{excl}")
    print(f"    prev({r['prev_date']})={r['prev_close']:.0f} -> open={r['open']:.0f} high={r['high']:.0f} low={r['low']:.0f} close={r['close']:.0f} vol={r['volume']:,}")
    print(f"    gap_open={r['gap_open_pct']:.2%} gap_close={r['gap_close_pct']:.2%}")
    print(f"    reasons: {r['reasons']}")
    print(f"    entry={r['entry_price']:.0f} stop={r['stop_price']:.0f} exit={r['exit_price']:.0f} atr={r['atr_at_signal']:.0f}")
    print()

print(f"\n=== DIRECT OVERLAP (gap likely triggered stop): {len(direct_overlap)} ===\n")
for r in direct_overlap:
    excl = " [QUALITY-EXCLUDED]" if r.get('quality_excluded') else ""
    print(f"  {r['ticker']} {r['date']}{excl}")
    print(f"    gap_open={r['gap_open_pct']:.2%} stop={r['stop_price']:.0f} low={r['low']:.0f}")
    print()

# Save
with open('corp_action_analysis.json', 'w') as f:
    json.dump({
        'total_same_bar_stops': len(same_bar_stops),
        'suspicious_count': len(corp_action_candidates),
        'direct_overlap_count': len(direct_overlap),
        'candidates': corp_action_candidates,
        'direct_overlap': direct_overlap,
    }, f, indent=2, default=str)

print("Saved to corp_action_analysis.json")