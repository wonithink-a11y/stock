"""Upbit 공개 캔들(GET /v1/candles/days)을 A2aProvider와 같은 DataFrame 모양
({market: DataFrame[open,high,low,close,volume]}, date 인덱스)으로 바꾼다.

engine.data.priceProvider.PriceProvider ABC는 구현하지 않는다 - manifest_hash/
coverage는 커밋된 백필 데이터의 계보 추적용 개념이고, 매번 새로 fetch하는
라이브 캔들에는 대응 개념이 없다(억지로 채우면 항상 같은 값이 나오는 죽은
필드가 된다). 이 모듈은 순수 변환 함수 하나만 제공한다 - paperEngine.
scan_signals()가 기대하는 {ticker: DataFrame} 모양만 맞추면 그 함수를
무수정으로 재사용할 수 있다(업비트-연동-2026-08-27 계획 문서 "재사용 확인"
참고 - scan_signals()는 bars_by_ticker를 미리 채워 넘기면 TradingCalendar를
만들기만 하고 안 쓴다).
"""
import pandas as pd

from .upbitClient import UpbitClient


def load_bars(markets, count=200, client=None):
    """markets: iterable of Upbit market codes(예: 'KRW-BTC'). 반환:
    {market: DataFrame[open,high,low,close,volume]}, date(Timestamp) 오름차순
    인덱스 - A2aProvider.load()와 같은 컬럼명·인덱스 규약이라 strategies/*/
    rule.py(예: dummy_sma20)를 무수정으로 재사용할 수 있다."""
    client = client or UpbitClient()
    bars = {}
    for market in markets:
        raw = client.get_candles_days(market, count=count)
        if not raw:
            continue
        rows = []
        for c in reversed(raw):  # 업비트는 최신순 - 오름차순으로 뒤집는다
            rows.append({
                "date": c["candle_date_time_kst"][:10],
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
