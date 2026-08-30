#!/usr/bin/env python3
"""
Fetch official Congressional PTR (Periodic Transaction Report) data from:
1. House Clerk - https://disclosures-clerk.house.gov/
2. Senate - https://www.senate.gov/reference/financial_disclosures.htm

Data sources:
- House: https://disclosures-clerk.house.gov/public_disc/financial-pdfs/ (PDFs) + XML bulk
- Senate: Bulk data at https://efdsearch.senate.gov/search/report/data/

This script downloads and parses official PTR data.
"""
import os
import re
import time
import json
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = REPO_ROOT / "research" / "strategy-lab" / "congress_trading" / "data"
RAW_DIR = DATA_DIR / "raw"
PARSED_DIR = DATA_DIR / "parsed"

for d in [RAW_DIR, PARSED_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def download_file(url: str, dest: Path, max_retries: int = 3) -> bool:
    """Download file with retries."""
    for attempt in range(max_retries):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            r = requests.get(url, headers=headers, timeout=60, stream=True)
            r.raise_for_status()
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return False


def fetch_house_ptr_bulk() -> Optional[Path]:
    """
    House Clerk provides bulk PTR data as ZIP of XML files.
    URL pattern: https://disclosures-clerk.house.gov/public_disc/ptr/ptr_all.zip
    Or yearly: ptr_2024.zip, ptr_2023.zip, etc.
    """
    print("Fetching House PTR bulk data...")
    
    base_url = "https://disclosures-clerk.house.gov/public_disc/ptr/"
    
    # Try to get the index page to find available files
    try:
        r = requests.get(base_url, timeout=30)
        soup = BeautifulSoup(r.text, 'html.parser')
        links = soup.find_all('a', href=re.compile(r'ptr_\d{4}\.zip'))
        years = sorted(set(re.search(r'ptr_(\d{4})\.zip', link['href']).group(1) for link in links))
        print(f"  Found House PTR years: {years}")
    except Exception as e:
        print(f"  Could not parse index, trying known years: {e}")
        years = [str(y) for y in range(2012, datetime.now().year + 1)]
    
    downloaded = []
    for year in years:
        url = f"{base_url}ptr_{year}.zip"
        dest = RAW_DIR / f"house_ptr_{year}.zip"
        if dest.exists():
            print(f"  {year}: already exists")
            downloaded.append(dest)
            continue
        print(f"  Downloading {year}...")
        if download_file(url, dest):
            downloaded.append(dest)
        time.sleep(1)
    
    return downloaded[-1] if downloaded else None


def fetch_senate_ptr_bulk() -> Optional[Path]:
    """
    Senate provides bulk data via efdsearch.senate.gov
    The bulk data endpoint: https://efdsearch.senate.gov/search/report/data/
    Returns JSON with all PTR filings.
    """
    print("Fetching Senate PTR data...")
    
    url = "https://efdsearch.senate.gov/search/report/data/"
    dest = RAW_DIR / "senate_ptr.json"
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.post(url, headers=headers, timeout=120)
        r.raise_for_status()
        data = r.json()
        with open(dest, 'w') as f:
            json.dump(data, f)
        print(f"  Downloaded {len(data.get('data', []))} records")
        return dest
    except Exception as e:
        print(f"  Senate fetch failed: {e}")
        return None


def parse_house_ptr_xml(xml_content: str) -> List[Dict]:
    """Parse a single House PTR XML file."""
    transactions = []
    try:
        root = ET.fromstring(xml_content)
        
        # Extract member info
        member_info = root.find('.//Member')
        if member_info is None:
            return transactions
        
        member_name = member_info.findtext('Name', '').strip()
        member_state = member_info.findtext('State', '').strip()
        member_district = member_info.findtext('District', '').strip()
        member_chamber = 'House'
        
        # Find all transactions
        for trans in root.findall('.//Transaction'):
            asset = trans.findtext('AssetName', '').strip()
            ticker = trans.findtext('Ticker', '').strip()
            trans_type = trans.findtext('TransactionType', '').strip()  # Purchase, Sale, Exchange
            trans_date = trans.findtext('TransactionDate', '').strip()
            filing_date = trans.findtext('FilingDate', '').strip()
            amount = trans.findtext('Amount', '').strip()
            is_amendment = trans.findtext('AmendmentIndicator', '').strip()
            
            # Parse amount range
            amount_low, amount_high = parse_amount_range(amount)
            
            transactions.append({
                'politician': member_name,
                'chamber': member_chamber,
                'state': member_state,
                'district': member_district,
                'party': None,  # Need separate lookup
                'ticker': ticker,
                'asset_name': asset,
                'transaction_type': trans_type,  # Purchase/Sale/Exchange
                'buy_sell': 'BUY' if 'Purchase' in trans_type else ('SELL' if 'Sale' in trans_type else None),
                'transaction_date': trans_date,
                'filing_date': filing_date,
                'amount_range': amount,
                'amount_low': amount_low,
                'amount_high': amount_high,
                'is_amendment': is_amendment == 'true',
            })
    except ET.ParseError as e:
        print(f"  XML parse error: {e}")
    return transactions


def parse_amount_range(amount_str: str) -> tuple:
    """Parse amount range like '$1,001 - $15,000' or '$100,001 - $250,000'."""
    if not amount_str:
        return None, None
    # Remove $ and commas
    clean = amount_str.replace('$', '').replace(',', '')
    # Match patterns
    m = re.search(r'([\d,]+)\s*-\s*([\d,]+)', clean)
    if m:
        return int(m.group(1).replace(',', '')), int(m.group(2).replace(',', ''))
    # Single value like "Over $1,000,000"
    m = re.search(r'Over\s+([\d,]+)', clean)
    if m:
        return int(m.group(1).replace(',', '')), None
    return None, None


def parse_house_ptr_zips(zip_paths: List[Path]) -> pd.DataFrame:
    """Parse all House PTR ZIP files."""
    all_transactions = []
    
    for zip_path in zip_paths:
        print(f"  Parsing {zip_path.name}...")
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                for name in zf.namelist():
                    if name.endswith('.xml'):
                        with zf.open(name) as f:
                            content = f.read().decode('utf-8', errors='ignore')
                            transactions = parse_house_ptr_xml(content)
                            all_transactions.extend(transactions)
        except Exception as e:
            print(f"    Error parsing {zip_path}: {e}")
    
    return pd.DataFrame(all_transactions)


def parse_senate_ptr_json(json_path: Path) -> pd.DataFrame:
    """Parse Senate PTR JSON data."""
    with open(json_path) as f:
        data = json.load(f)
    
    transactions = []
    records = data.get('data', [])
    
    for rec in records:
        # Senate data structure
        member_name = rec.get('name', '').strip()
        state = rec.get('state', '').strip()
        chamber = 'Senate'
        
        for trans in rec.get('transactions', []):
            ticker = trans.get('ticker', '').strip()
            asset = trans.get('asset_name', '').strip()
            trans_type = trans.get('type', '').strip()
            trans_date = trans.get('transaction_date', '').strip()
            filing_date = trans.get('filing_date', '').strip()
            amount = trans.get('amount', '').strip()
            is_amendment = trans.get('amendment', False)
            
            amount_low, amount_high = parse_amount_range(amount)
            
            transactions.append({
                'politician': member_name,
                'chamber': chamber,
                'state': state,
                'district': None,
                'party': None,
                'ticker': ticker,
                'asset_name': asset,
                'transaction_type': trans_type,
                'buy_sell': 'BUY' if trans_type.lower() == 'purchase' else ('SELL' if trans_type.lower() == 'sale' else None),
                'transaction_date': trans_date,
                'filing_date': filing_date,
                'amount_range': amount,
                'amount_low': amount_low,
                'amount_high': amount_high,
                'is_amendment': is_amendment,
            })
    
    return pd.DataFrame(transactions)


def fetch_quiver_crossref() -> Optional[pd.DataFrame]:
    """
    Fetch Quiver Quantitative congressional trading data for cross-validation.
    Note: This requires an API key or web scraping. 
    Quiver has a public API at https://api.quiverquant.com/beta/live/congresstrading
    """
    print("Fetching Quiver Quantitative data (if available)...")
    
    # Try public endpoint
    url = "https://api.quiverquant.com/beta/live/congresstrading"
    try:
        r = requests.get(url, timeout=30)
        if r.status_code == 200:
            data = r.json()
            df = pd.DataFrame(data)
            dest = RAW_DIR / "quiver_congress.json"
            df.to_json(dest, orient='records')
            print(f"  Downloaded {len(df)} Quiver records")
            return df
    except Exception as e:
        print(f"  Quiver fetch failed (may need API key): {e}")
    
    return None


def add_party_info(df: pd.DataFrame) -> pd.DataFrame:
    """Add party affiliation from a reference file or lookup."""
    # This would ideally come from a separate reference file
    # For now, we'll leave party as None and note it needs enrichment
    return df


def validate_pit_compliance(df: pd.DataFrame) -> Dict:
    """Validate PIT compliance of the dataset."""
    issues = []
    
    # Check for missing filing dates
    missing_filing = df['filing_date'].isna().sum()
    if missing_filing > 0:
        issues.append(f"Missing filing_date: {missing_filing} records")
    
    # Check for missing transaction dates
    missing_trans = df['transaction_date'].isna().sum()
    if missing_trans > 0:
        issues.append(f"Missing transaction_date: {missing_trans} records")
    
    # Check filing_date >= transaction_date (PIT requirement)
    df_dates = df.copy()
    df_dates['transaction_date'] = pd.to_datetime(df_dates['transaction_date'], errors='coerce')
    df_dates['filing_date'] = pd.to_datetime(df_dates['filing_date'], errors='coerce')
    
    future_info = df_dates[df_dates['filing_date'] < df_dates['transaction_date']]
    if len(future_info) > 0:
        issues.append(f"filing_date < transaction_date (PIT violation): {len(future_info)} records")
    
    # Check lag distribution
    valid = df_dates.dropna(subset=['transaction_date', 'filing_date'])
    valid['lag_days'] = (valid['filing_date'] - valid['transaction_date']).dt.days
    
    return {
        'total_records': len(df),
        'issues': issues,
        'lag_stats': valid['lag_days'].describe().to_dict() if len(valid) > 0 else {},
        'date_range': {
            'transaction': (df_dates['transaction_date'].min(), df_dates['transaction_date'].max()),
            'filing': (df_dates['filing_date'].min(), df_dates['filing_date'].max()),
        }
    }


def main():
    print("=" * 60)
    print("Congressional Trading Data Fetch & Validation")
    print("=" * 60)
    
    # 1. Fetch House data
    house_zips = fetch_house_ptr_bulk()
    if house_zips:
        if isinstance(house_zips, list):
            house_df = parse_house_ptr_zips(house_zips)
        else:
            house_df = parse_house_ptr_zips([house_zips])
        print(f"House transactions: {len(house_df)}")
        house_df.to_parquet(PARSED_DIR / "house_ptr.parquet")
    else:
        print("No House data fetched")
        house_df = pd.DataFrame()
    
    # 2. Fetch Senate data
    senate_json = fetch_senate_ptr_bulk()
    if senate_json:
        senate_df = parse_senate_ptr_json(senate_json)
        print(f"Senate transactions: {len(senate_df)}")
        senate_df.to_parquet(PARSED_DIR / "senate_ptr.parquet")
    else:
        print("No Senate data fetched")
        senate_df = pd.DataFrame()
    
    # 3. Combine
    combined = pd.concat([house_df, senate_df], ignore_index=True)
    print(f"\nCombined: {len(combined)} transactions")
    
    # 4. Add party info (placeholder)
    combined = add_party_info(combined)
    
    # 5. Save combined
    combined.to_parquet(PARSED_DIR / "congress_ptr_combined.parquet")
    combined.to_csv(PARSED_DIR / "congress_ptr_combined.csv", index=False)
    
    # 6. Validate PIT compliance
    print("\n" + "=" * 60)
    print("PIT Compliance Validation")
    print("=" * 60)
    validation = validate_pit_compliance(combined)
    print(json.dumps(validation, indent=2, default=str))
    
    # 7. Try Quiver cross-ref
    quiver_df = fetch_quiver_crossref()
    if quiver_df is not None:
        quiver_df.to_parquet(PARSED_DIR / "quiver_congress.parquet")
    
    # 8. Summary stats
    print("\n" + "=" * 60)
    print("Data Coverage Summary")
    print("=" * 60)
    print(f"Total transactions: {len(combined)}")
    print(f"BUY: {(combined['buy_sell']=='BUY').sum()}")
    print(f"SELL: {(combined['buy_sell']=='SELL').sum()}")
    print(f"Unique politicians: {combined['politician'].nunique()}")
    print(f"Unique tickers: {combined['ticker'].nunique()}")
    print(f"House: {(combined['chamber']=='House').sum()}")
    print(f"Senate: {(combined['chamber']=='Senate').sum()}")
    if 'filing_date' in combined:
        combined['filing_date'] = pd.to_datetime(combined['filing_date'], errors='coerce')
        print(f"Filing date range: {combined['filing_date'].min()} to {combined['filing_date'].max()}")
    
    return combined


if __name__ == "__main__":
    main()