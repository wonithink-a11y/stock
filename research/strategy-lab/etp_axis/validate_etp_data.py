#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ETP 데이터 품질 검사기 — 순수 함수(네트워크 불필요) + selftest.

검사 항목: duplicate date, missing trading day(calendar 대조), OHLC 관계,
close<=0, volume<0, turnover<0, 상장 전/폐지 후 데이터.
"""
import numpy as np
import pandas as pd


def validate(prices: pd.DataFrame, listing_date=None, delisting_date=None,
             trading_days=None) -> dict:
    """prices: collect_etp_daily.SCHEMA 순서의 표준 프레임."""
    res = {}
    dates = prices["date"].tolist()
    res["rows"] = len(prices)
    res["duplicate_dates"] = int(len(dates) - len(set(dates)))

    if trading_days is not None and len(dates):
        td = [d for d in trading_days if dates[0] <= d <= dates[-1]]
        missing = sorted(set(td) - set(dates))
        res["missing_trading_days"] = len(missing)
        res["missing_trading_days_sample"] = missing[:10]
    else:
        res["missing_trading_days"] = None

    o, h, l, c = (prices[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = prices["volume"].to_numpy(float)
    t = prices["turnover"].to_numpy(float) if "turnover" in prices else None

    res["low_gt_high"] = int((l > h).sum())
    res["open_out_of_range"] = int(((o < l) | (o > h)).sum())
    res["close_out_of_range"] = int(((c < l) | (c > h)).sum())
    res["close_le_zero"] = int((c <= 0).sum())
    res["volume_lt_zero"] = int((v < 0).sum())
    res["turnover_lt_zero"] = int((t[t < 0]).size) if t is not None else None

    if listing_date:
        pre = [d for d in dates if d < listing_date]
        res["pre_listing_rows"] = len(pre); res["pre_listing_sample"] = pre[:5]
    if delisting_date:
        post = [d for d in dates if d > delisting_date]
        res["post_delisting_rows"] = len(post); res["post_delisting_sample"] = post[:5]
    return res


def selftest():
    """네트워크 없이 검증 로직을 확인하는 fixture 3개."""
    results = {}

    # fixture 1: OHLC 위반(low>high)과 close<=0 탐지
    bad = pd.DataFrame({
        "date": ["D1", "D2", "D3"], "symbol": "X", "open": [100.0, 100.0, 100.0],
        "high": [110.0, 105.0, 105.0], "low": [90.0, 106.0, 95.0],
        "close": [105.0, 104.0, -1.0], "volume": [1, 1, 1], "turnover": [np.nan] * 3})
    r = validate(bad)
    results["fixture1_ohlc_violations"] = (
        r["low_gt_high"] == 1 and r["close_le_zero"] == 1)

    # fixture 2: 중복 날짜 + calendar 결측 탐지
    dup = pd.DataFrame({
        "date": ["2026-01-05", "2026-01-05", "2026-01-07"],
        "symbol": "X", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
        "volume": 1, "turnover": np.nan})
    cal = ["2026-01-05", "2026-01-06", "2026-01-07"]
    r = validate(dup, trading_days=cal)
    results["fixture2_dup_and_missing"] = (
        r["duplicate_dates"] == 1 and r["missing_trading_days"] == 1)

    # fixture 3: 상장 전/폐지 후 경계 검사
    edge = pd.DataFrame({
        "date": ["2019-12-30", "2020-01-02", "2027-06-01"],
        "symbol": "X", "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
        "volume": 1, "turnover": np.nan})
    r = validate(edge, listing_date="2020-01-01", delisting_date="2027-01-01")
    results["fixture3_listing_boundary"] = (
        r["pre_listing_rows"] == 1 and r["post_delisting_rows"] == 1)

    ok = all(results.values())
    return ok, results


if __name__ == "__main__":
    import json
    ok, res = selftest()
    print(json.dumps({"selftest_ok": ok, "fixtures": res}, ensure_ascii=False, indent=2))
