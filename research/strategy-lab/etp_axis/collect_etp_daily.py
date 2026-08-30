#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ETP 데이터축 공통 유틸 — 기존 프로젝트 접근 방식(pykrx) 재사용.

주의(실측 2026-08-23):
 - pykrx 1.2.8의 get_etf_ticker_list()/get_etn_ticker_list()는 내부에서
   지수/영업일 조회를 하며, KRX_ID/KRX_PW 로그인 세션이 없으면 IndexError로 실패한다.
 - 개별종목 일봉(get_market_ohlcv)은 로그인 없이 동작한다(price.v1.json 실측과 동일).
 - 소스 역사 경계: 개별종목 일봉은 2014-05-30(069500 실측) 이후만 제공된다.
"""
import numpy as np
import pandas as pd
from pykrx import stock

SCHEMA = ["date", "symbol", "open", "high", "low", "close",
          "volume", "turnover"]


def fetch_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    """KRX 일봉을 표준 스키마로 정규화한다. turnover는 소스 미제공으로 null."""
    df = stock.get_market_ohlcv(start, end, symbol)
    if len(df) == 0:
        return pd.DataFrame(columns=SCHEMA)
    out = pd.DataFrame({
        "date": [str(x)[:10] for x in df.index],
        "symbol": symbol,
        "open": df["시가"].to_numpy(float),
        "high": df["고가"].to_numpy(float),
        "low": df["저가"].to_numpy(float),
        "close": df["종가"].to_numpy(float),
        "volume": df["거래량"].to_numpy(float),
        "turnover": np.nan,  # 소스 미제공 — 추정 금지(null 유지)
    })
    return out.reset_index(drop=True)


def list_etf_codes():
    """ETF 코드 목록. KRX 로그인 세션 필요(미설정 환경에서는 RuntimeError)."""
    try:
        return list(stock.get_etf_ticker_list())
    except Exception as e:
        raise RuntimeError(
            f"get_etf_ticker_list failed ({e}); KRX_ID/KRX_PW 세션이 필요하다"
            "(A4/A8 수집기와 동일 자격)") from e


def list_etn_codes():
    try:
        return list(stock.get_etn_ticker_list())
    except Exception as e:
        raise RuntimeError(
            f"get_etn_ticker_list failed ({e}); KRX_ID/KRX_PW 세션이 필요하다") from e
