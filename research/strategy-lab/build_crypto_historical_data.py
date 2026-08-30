#!/usr/bin/env python
"""Upbit에서 KRW 마켓 주요 코인의 과거 일봉/4시간봉 데이터를 수집해 Parquet로 저장한다.

- Upbit 공개 API(v1/candles/days, v1/candles/minutes/240) 사용
- 일봉은 count=200 제한 → to 파라미터로 페이지네이션하여 수년 치 확보
- 4시간봉도 동일 방식(count=200, to로 페이지네이션)
- 저장 경로: research/strategy-lab/data/crypto/{daily,4h}/{market}.parquet
- 증분 업데이트 지원(기존 파일 있으면 최신일부터만 추가 수집)
"""
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.live.upbitClient import UpbitClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data" / "crypto"

# 주요 유동성 코인 (KRW 마켓, Upbit 상장 기준)
TARGET_MARKETS = [
    "KRW-BTC", "KRW-ETH", "KRW-SOL", "KRW-XRP", "KRW-ADA",
    "KRW-DOGE", "KRW-AVAX", "KRW-DOT", "KRW-LINK",
    "KRW-ATOM", "KRW-NEAR", "KRW-ARB", "KRW-OP", "KRW-UNI",
]

# 수집 기간 설정
DAILY_LOOKBACK_DAYS = 1000      # 일봉: 약 3년
INTRADAY_LOOKBACK_DAYS = 365    # 4시간봉: 약 1년 (API 제한 고려)
CHUNK_SIZE = 200                # Upbit API 최대 count
RATE_LIMIT_DELAY = 0.11         # 초당 10회 제한에 여유


def fetch_daily_chunk(client, market, count=CHUNK_SIZE, to=None):
    """일봉 한 청크 수집. 반환: list[dict] (최신순)"""
    return client.get_candles_days(market, count=count, to=to)


def fetch_4h_chunk(client, market, count=CHUNK_SIZE, to=None):
    """4시간봉 한 청크 수집. 업비트 분봉 엔드포인트: /v1/candles/minutes/240"""
    from engine.live.upbitClient import _request, BASE_URL, _RATE_LIMITER
    params = {"market": market, "count": count}
    if to:
        params["to"] = to
    _RATE_LIMITER.wait()
    r = _request("GET", BASE_URL + "/v1/candles/minutes/240", params=params, timeout=10)
    body = r.json()
    if r.status_code >= 400 or (isinstance(body, dict) and "error" in body):
        raise RuntimeError(f"4h 캔들 조회 실패({market}): {body}")
    return body


def chunks_to_dataframe(raw_chunks, is_daily=True):
    """여러 청크(raw list)를 합쳐 정렬된 DataFrame으로 변환.
    컬럼: open, high, low, close, volume, date(Timestamp index)"""
    rows = []
    for chunk in raw_chunks:
        for c in reversed(chunk):  # 각 청크는 최신순 → 오름차순으로 뒤집기
            if is_daily:
                dt_key = "candle_date_time_kst"
                rows.append({
                    "date": c[dt_key][:10],
                    "open": float(c["opening_price"]),
                    "high": float(c["high_price"]),
                    "low": float(c["low_price"]),
                    "close": float(c["trade_price"]),
                    "volume": float(c["candle_acc_trade_volume"]),
                })
            else:
                # 4시간봉: candle_date_time_kst가 "2026-08-27T12:00:00" 형태
                dt_key = "candle_date_time_kst"
                rows.append({
                    "date": c[dt_key][:19],  # 초 단위까지
                    "open": float(c["opening_price"]),
                    "high": float(c["high_price"]),
                    "low": float(c["low_price"]),
                    "close": float(c["trade_price"]),
                    "volume": float(c["candle_acc_trade_volume"]),
                })
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset="date", keep="last").sort_values("date")
    return df.set_index("date")


def load_existing(market, timeframe):
    """기존 저장 파일 로드. 없으면 빈 DataFrame."""
    path = DATA_DIR / timeframe / f"{market}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def save_data(df, market, timeframe):
    """DataFrame을 Parquet로 저장."""
    path = DATA_DIR / timeframe / f"{market}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    print(f"  Saved: {path} ({len(df)} rows, {df.index[0].date()} ~ {df.index[-1].date()})")


def fetch_full_history(client, market, timeframe, lookback_days):
    """전체 히스토리 수집(증분 지원)."""
    existing = load_existing(market, timeframe)
    
    # 현재 시간 (KST, timezone-naive로 통일)
    now_kst = pd.Timestamp.now(tz="UTC").tz_convert("Asia/Seoul").tz_localize(None)
    
    if not existing.empty:
        # 기존 데이터의 다음 날부터 수집
        last_date = existing.index[-1]
        if timeframe == "daily":
            to_param = (last_date + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        else:
            to_param = (last_date + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%S")
        print(f"  {market} {timeframe}: incremental from {last_date.date()}")
    else:
        # 신규 수집: 현재로부터 lookback_days 전까지
        to_param = None
        print(f"  {market} {timeframe}: full fetch ({lookback_days} days)")
    
    all_chunks = []
    fetched_days = 0
    max_chunks = (lookback_days // (CHUNK_SIZE if timeframe == "daily" else CHUNK_SIZE * 4)) + 5
    
    for chunk_idx in range(max_chunks):
        try:
            if timeframe == "daily":
                chunk = fetch_daily_chunk(client, market, to=to_param)
            else:
                chunk = fetch_4h_chunk(client, market, to=to_param)
        except Exception as e:
            print(f"    Error on chunk {chunk_idx+1}: {e}")
            break
        
        if not chunk:
            print(f"    No more data (chunk {chunk_idx+1})")
            break
        
        all_chunks.append(chunk)
        fetched_days += len(chunk)
        
        # 다음 청크를 위한 to 파라미터 (가장 오래된 캔들의 시간)
        oldest = chunk[-1]["candle_date_time_kst"]
        to_param = oldest
        
        # 목표 기간 도달 시 중단
        if timeframe == "daily":
            oldest_date = pd.Timestamp(oldest[:10])
            if (now_kst.normalize() - oldest_date).days >= lookback_days:
                print(f"    Reached lookback target ({lookback_days} days)")
                break
        else:
            oldest_dt = pd.Timestamp(oldest[:19])
            if (now_kst - oldest_dt).days >= lookback_days:
                print(f"    Reached lookback target ({lookback_days} days)")
                break
        
        time.sleep(RATE_LIMIT_DELAY)
    
    if not all_chunks:
        print(f"  {market} {timeframe}: no new data")
        return existing
    
    new_df = chunks_to_dataframe(all_chunks, is_daily=(timeframe == "daily"))
    
    if new_df.empty:
        print(f"  {market} {timeframe}: fetched data is empty")
        return existing
    
    # 기존 데이터와 병합 (중복 제거)
    if not existing.empty:
        combined = pd.concat([existing, new_df])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    else:
        combined = new_df
    
    return combined


def main():
    client = UpbitClient()
    
    print("=" * 60)
    print("Crypto Historical Data Fetcher (Upbit KRW Market)")
    print("=" * 60)
    
    # 일봉 수집
    print("\n[1/2] Fetching DAILY candles...")
    for market in TARGET_MARKETS:
        try:
            df = fetch_full_history(client, market, "daily", DAILY_LOOKBACK_DAYS)
            save_data(df, market, "daily")
        except Exception as e:
            print(f"  {market} DAILY FAILED: {e}")
        time.sleep(RATE_LIMIT_DELAY)
    
    # 4시간봉 수집
    print("\n[2/2] Fetching 4-HOUR candles...")
    for market in TARGET_MARKETS:
        try:
            df = fetch_full_history(client, market, "4h", INTRADAY_LOOKBACK_DAYS)
            save_data(df, market, "4h")
        except Exception as e:
            print(f"  {market} 4H FAILED: {e}")
        time.sleep(RATE_LIMIT_DELAY)
    
    print("\nDone.")


if __name__ == "__main__":
    main()