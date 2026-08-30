#!/usr/bin/env python3
"""
Alternative data sources for Congressional trading data.

Known public sources:
1. https://github.com/awesomedata/apis - lists congressional trading APIs
2. https://www.quiverquant.com - has API (paid)
3. https://house-stock-watcher.com - has data (may have CSV export)
4. https://github.com/mgckid/congress-trading - mirror repo
5. https://github.com/bpb27/congress_trading_data - data mirror

Let's try to find a usable public CSV/JSON dataset.
"""
import json
import requests
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
RAW_DIR = REPO_ROOT / "research" / "strategy-lab" / "congress_trading" / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def try_github_mirrors():
    """Try known GitHub repos that mirror congressional trading data."""
    mirrors = [
        "https://raw.githubusercontent.com/mgckid/congress-trading/main/data/congress_trading.csv",
        "https://raw.githubusercontent.com/bpb27/congress_trading_data/main/data/all_transactions.csv",
        "https://raw.githubusercontent.com/karolzak/congress-trading-data/main/data/transactions.csv",
    ]
    
    for url in mirrors:
        try:
            print(f"Trying: {url}")
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                dest = RAW_DIR / f"github_mirror_{url.split('/')[-2]}.csv"
                dest.write_bytes(r.content)
                print(f"  SUCCESS: Downloaded to {dest}")
                return dest
        except Exception as e:
            print(f"  Failed: {e}")
    return None


def try_house_stock_watcher():
    """Try house-stock-watcher data sources."""
    urls = [
        "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json",
        "https://house-stock-watcher.s3.amazonaws.com/data/all_transactions.json",
    ]
    for url in urls:
        try:
            print(f"Trying: {url}")
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                dest = RAW_DIR / "house_stock_watcher.json"
                dest.write_bytes(r.content)
                print(f"  SUCCESS: Downloaded to {dest}")
                return dest
        except Exception as e:
            print(f"  Failed: {e}")
    return None


def create_sample_data():
    """Create a minimal sample dataset for testing the event study framework."""
    print("Creating sample test data...")
    
    # This is just for framework validation - real data needed for actual analysis
    import pandas as pd
    import numpy as np
    from datetime import datetime, timedelta
    
    # Create sample data matching the expected schema
    np.random.seed(42)
    n = 1000
    
    politicians = [f"Rep_{i}" for i in range(50)] + [f"Sen_{i}" for i in range(15)]
    tickers = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM', 'V', 'UNH',
               'JNJ', 'WMT', 'PG', 'MA', 'HD', 'DIS', 'BAC', 'ADBE', 'CRM', 'NFLX']
    
    start = datetime(2012, 1, 1)
    end = datetime(2024, 12, 31)
    
    data = []
    for i in range(n):
        trans_date = start + timedelta(days=np.random.randint(0, (end - start).days))
        # Filing lag: 0-45 days
        lag = np.random.randint(0, 46)
        filing_date = trans_date + timedelta(days=lag)
        
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
            'amount_range': f"${np.random.randint(1, 500)*1000:,} - ${np.random.randint(500, 1000)*1000:,}",
            'amount_low': np.random.randint(1, 500) * 1000,
            'amount_high': np.random.randint(500, 1000) * 1000,
            'is_amendment': False,
        })
    
    df = pd.DataFrame(data)
    dest = RAW_DIR / "sample_congress_data.parquet"
    df.to_parquet(dest)
    print(f"Created sample data: {len(df)} records at {dest}")
    return dest


def main():
    print("=" * 60)
    print("Congressional Trading Data - Alternative Sources")
    print("=" * 60)
    
    # Try GitHub mirrors
    print("\n1. Trying GitHub mirrors...")
    result = try_github_mirrors()
    
    # Try House Stock Watcher
    print("\n2. Trying House Stock Watcher...")
    result = result or try_house_stock_watcher()
    
    if result is None:
        print("\n3. No public data source accessible. Creating sample data for framework validation...")
        result = create_sample_data()
    
    print(f"\nData file: {result}")
    return result


if __name__ == "__main__":
    main()