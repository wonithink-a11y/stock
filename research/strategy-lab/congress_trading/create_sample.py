import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

np.random.seed(42)
n = 2000

politicians = [f'Rep_{i}' for i in range(50)] + [f'Sen_{i}' for i in range(15)]
tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'V', 'UNH',
           'JNJ', 'WMT', 'PG', 'MA', 'HD', 'DIS', 'BAC', 'ADBE', 'CRM', 'NFLX']

start = datetime(2012, 1, 1)
end = datetime(2024, 12, 31)

data = []
for i in range(n):
    trans_date = start + timedelta(days=np.random.randint(0, (end - start).days))
    lag = np.random.randint(0, 46)
    filing_date = trans_date + timedelta(days=lag)
    
    low = np.random.randint(1, 500) * 1000
    high = np.random.randint(500, 1000) * 1000
    
    data.append({
        'politician': np.random.choice(politicians),
        'chamber': np.random.choice(['House', 'Senate'], p=[0.8, 0.2]),
        'state': np.random.choice(['CA', 'TX', 'NY', 'FL', 'PA', 'IL', 'OH', 'GA', 'NC', 'MI']),
        'district': np.random.randint(1, 54) if np.random.random() < 0.8 else None,
        'party': np.random.choice(['Democrat', 'Republican']),
        'ticker': np.random.choice(tickers),
        'asset_name': np.random.choice(tickers),
        'transaction_type': 'Purchase',
        'buy_sell': 'BUY',
        'transaction_date': trans_date.strftime('%Y-%m-%d'),
        'filing_date': filing_date.strftime('%Y-%m-%d'),
        'amount_range': f"${low:,} - ${high:,}",
        'amount_low': low,
        'amount_high': high,
        'is_amendment': False,
    })

df = pd.DataFrame(data)
dest = Path('research/strategy-lab/congress_trading/data/parsed/congress_ptr_combined.parquet')
dest.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(dest)
print(f'Created sample data: {len(df)} records at {dest}')