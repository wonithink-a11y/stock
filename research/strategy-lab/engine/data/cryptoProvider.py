"""Crypto data provider for Upbit - fetches daily and 4-hour candles.
Returns DataFrames with same column convention as A2aProvider:
{market: DataFrame[open, high, low, close, volume]}, date index ascending.
"""
import time
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
BASE_URL = "https://api.upbit.com"

# Upbit rate limit: 10 req/sec for public endpoints
_RATE_LIMIT = 0.11  # seconds between calls

_last_call = 0.0


def _rate_limit():
    global _last_call
    now = time.monotonic()
    wait = _last_call + _RATE_LIMIT - now
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def fetch_daily_candles(market: str, count: int = 500, to: str | None = None) -> list[dict]:
    """Fetch daily candles from Upbit. Returns raw response (newest first)."""
    _rate_limit()
    params = {"market": market, "count": count}
    if to:
        params["to"] = to
    r = requests.get(f"{BASE_URL}/v1/candles/days", params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"Upbit error ({market}): {data}")
    return data


def fetch_minute_candles(market: str, unit: int = 240, count: int = 500, to: str | None = None) -> list[dict]:
    """Fetch minute candles (unit minutes). Upbit supports 1,3,5,10,15,30,60,240.
    unit=240 gives 4-hour candles. Returns raw response (newest first)."""
    _rate_limit()
    params = {"market": market, "count": count}
    if to:
        params["to"] = to
    r = requests.get(f"{BASE_URL}/v1/candles/minutes/{unit}", params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError(f"Upbit error ({market}): {data}")
    return data


def load_crypto_bars(
    markets: list[str],
    timeframe: str = "D",  # "D" for daily, "4H" for 4-hour
    count: int = 500,
    to: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Load crypto bars for multiple markets.
    
    Args:
        markets: List of Upbit market codes (e.g., ["KRW-BTC", "KRW-ETH"])
        timeframe: "D" for daily, "4H" for 4-hour candles
        count: Number of candles to fetch (max 200 per call for daily, we chain calls)
        to: End date in ISO format (e.g., "2026-08-27 00:00:00")
    
    Returns:
        {market: DataFrame[open, high, low, close, volume]}, date index ascending
    """
    if timeframe == "D":
        fetch_fn = fetch_daily_candles
    elif timeframe == "4H":
        fetch_fn = lambda m, c, t: fetch_minute_candles(m, unit=240, count=c, to=t)
    else:
        raise ValueError(f"Unknown timeframe: {timeframe}")

    bars = {}
    for market in markets:
        all_raw = []
        remaining = count
        cursor = to
        while remaining > 0:
            batch = min(remaining, 200)
            raw = fetch_fn(market, batch, cursor)
            if not raw:
                break
            all_raw.extend(raw)
            if len(raw) < batch:
                break
            # Next call starts from the oldest candle we got
            oldest = raw[-1]["candle_date_time_kst"]
            cursor = oldest
            remaining -= batch
            # Small pause to be safe
            time.sleep(0.05)

        if not all_raw:
            continue

        rows = []
        for c in reversed(all_raw):  # Upbit returns newest first
            rows.append({
                "date": c["candle_date_time_kst"][:19] if timeframe == "4H" else c["candle_date_time_kst"][:10],
                "open": float(c["opening_price"]),
                "high": float(c["high_price"]),
                "low": float(c["low_price"]),
                "close": float(c["trade_price"]),
                "volume": float(c["candle_acc_trade_volume"]),
            })
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        bars[market] = df.set_index("date").sort_index()
    return bars


def load_crypto_bars_cached(
    markets: list[str],
    timeframe: str = "D",
    count: int = 500,
    cache_dir: Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Load crypto bars with local parquet caching."""
    if cache_dir is None:
        cache_dir = REPO_ROOT / "research" / "strategy-lab" / ".cache" / "crypto_bars"
    cache_dir.mkdir(parents=True, exist_ok=True)

    bars = {}
    for market in markets:
        safe_name = market.replace("-", "_")
        cache_file = cache_dir / f"{safe_name}_{timeframe}.parquet"

        if cache_file.exists():
            try:
                df = pd.read_parquet(cache_file)
                # Ensure we have enough data
                if len(df) >= count:
                    bars[market] = df.tail(count)
                    continue
            except Exception:
                pass

        # Fetch fresh data
        fresh = load_crypto_bars([market], timeframe=timeframe, count=count)
        if market in fresh:
            df = fresh[market]
            df.to_parquet(cache_file)
            bars[market] = df
    return bars


if __name__ == "__main__":
    # Quick test
    markets = ["KRW-BTC", "KRW-ETH", "KRW-SOL"]
    print("Fetching daily...")
    daily = load_crypto_bars(markets, timeframe="D", count=200)
    for m, df in daily.items():
        print(f"  {m}: {len(df)} bars, {df.index[0].date()} ~ {df.index[-1].date()}")

    print("\nFetching 4H...")
    h4 = load_crypto_bars(markets, timeframe="4H", count=200)
    for m, df in h4.items():
        print(f"  {m}: {len(df)} bars, {df.index[0]} ~ {df.index[-1]}")