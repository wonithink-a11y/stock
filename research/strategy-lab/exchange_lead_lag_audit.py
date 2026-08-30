#!/usr/bin/env python
"""Step 30 — Exchange Lead-Lag Audit.

Upbit KRW ↔ Binance USDT 간 가격 선행성(lead-lag) 연구 가용성 감사.
기존 데이터만 사용, 대량 수집 금지, 기존 파일 수정 금지.
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "exchange-lead-lag-audit-2026-08.json"
OUT_MD = HERE / "findings" / "exchange-lead-lag-audit-2026-08.md"

KRW_BASES = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "DOT", "ATOM", "AVAX",
             "LINK", "NEAR", "OP", "UNI", "ARB", "MATIC"]
USDT_28 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
           "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
           "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
           "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
           "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "ZECUSDT"]
KRW_TO_USDT = {b: f"{b}USDT" for b in KRW_BASES}


def load_krw_daily():
    data = {}
    for b in KRW_BASES:
        p = HERE / "data" / "crypto" / "daily" / f"KRW-{b}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if len(df) > 0:
                data[b] = df
    return data


def load_krw_4h():
    data = {}
    for b in KRW_BASES:
        p = HERE / "data" / "crypto" / "4h" / f"KRW-{b}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if len(df) > 0:
                data[b] = df
    return data


def load_usdt_basis_1h():
    data = {}
    for s in USDT_28:
        p = HERE / "data" / "crypto" / "basis" / "1h" / f"{s}_1h.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if len(df) > 0:
                data[s] = df
    return data


def load_usdt_basis_8h():
    data = {}
    for s in USDT_28:
        p = HERE / "data" / "crypto" / "basis" / f"{s}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if len(df) > 0:
                data[s] = df
    return data


def krw_to_utc(krw_df):
    """KRW KST naive datetime index → UTC datetime index."""
    # KRW daily/4h index는 KST naive (tz=None)
    # KST = UTC+9 → UTC = KST - 9h
    df = krw_df.copy()
    if isinstance(df.index, pd.DatetimeIndex):
        df.index = df.index - pd.Timedelta(hours=9)
        df.index = df.index.tz_localize("UTC")
    return df


def usdt_1h_to_kst_daily(usdt_1h):
    """USDT 1h mark_close → KST daily close (14:00 UTC bar = KST 24:00)."""
    df = usdt_1h.copy()
    df["kst_date"] = (df["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    # 14:00 UTC bar closes at 15:00 UTC = 24:00 KST
    df_14 = df[df["time"].dt.hour == 14]
    daily = df_14.groupby("kst_date")["mark_close"].last()
    daily.index.name = "date"
    return daily


def usdt_1h_to_kst_4h(usdt_1h):
    """USDT 1h → KST 4h bars (UTC 1h를 KST 4h로 리샘플)."""
    df = usdt_1h.copy()
    df["kst_time"] = df["time"] + pd.Timedelta(hours=9)
    df = df.set_index("kst_time")
    # 4h 리샘플: KST 00,04,08,12,16,20시 시작 바
    agg_dict = {
        "mark_close": "last",
        "mark_open": "first",
        "mark_high": "max",
        "mark_low": "min",
        "index_close": "last",
        "index_open": "first",
        "index_high": "max",
        "index_low": "min",
        "premium_close": "last",
        "premium_open": "first",
    }
    resampled = df.resample("4h").agg(agg_dict).dropna(subset=["mark_close"])
    return resampled


def main():
    out = {"design": {
        "purpose": "Upbit KRW ↔ Binance USDT lead-lag 연구 가용성 감사",
        "resolutions": ["1d", "4h", "1h"],
        "ref_date": "2023-05-21",
        "constraints": "기존 데이터만, 대량 수집 금지, 추정 금지",
    }}

    # 데이터 로드
    krw_daily = load_krw_daily()
    krw_4h = load_krw_4h()
    usdt_1h = load_usdt_basis_1h()
    usdt_8h = load_usdt_basis_8h()

    out["krw_daily_coverage"] = {}
    for b, df in krw_daily.items():
        out["krw_daily_coverage"][b] = {
            "rows": len(df),
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "freq": "daily",
            "tz": "KST (naive)",
        }

    out["krw_4h_coverage"] = {}
    for b, df in krw_4h.items():
        out["krw_4h_coverage"][b] = {
            "rows": len(df),
            "start": str(df.index.min().date()) if hasattr(df.index.min(), "date") else str(df.index.min()),
            "end": str(df.index.max().date()) if hasattr(df.index.max(), "date") else str(df.index.max()),
            "freq": "4h",
            "tz": "KST (naive)",
        }

    # USDT 1h → KST daily/4h 변환 및 coverage
    usdt_daily = {}
    usdt_4h = {}
    for s, df in usdt_1h.items():
        daily = usdt_1h_to_kst_daily(df)
        if daily is not None and len(daily) > 0:
            usdt_daily[s] = daily
        h4 = usdt_1h_to_kst_4h(df)
        if h4 is not None and len(h4) > 0:
            usdt_4h[s] = h4

    out["usdt_daily_coverage"] = {}
    for s, df in usdt_daily.items():
        out["usdt_daily_coverage"][s] = {
            "rows": len(df),
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "freq": "daily (KST 24:00 close)",
            "tz": "KST",
        }

    out["usdt_4h_coverage"] = {}
    for s, df in usdt_4h.items():
        out["usdt_4h_coverage"][s] = {
            "rows": len(df),
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "freq": "4h (KST)",
            "tz": "KST",
        }

    # 공통 종목 (KRW 15개 중 USDT에 있는 것)
    common_daily = []
    common_4h = []
    for b in KRW_BASES:
        usdt = KRW_TO_USDT.get(b)
        if usdt in usdt_daily and b in krw_daily:
            common_daily.append(b)
        if usdt in usdt_4h and b in krw_4h:
            common_4h.append(b)

    out["common_symbols"] = {
        "daily": common_daily,
        "4h": common_4h,
    }

    # 공통 기간 (2023-05-21 이후 교집합)
    ref = pd.Timestamp("2023-05-21")
    ref_utc = pd.Timestamp("2023-05-21", tz="UTC")
    common_period_daily = {}
    for b in common_daily:
        usdt = KRW_TO_USDT[b]
        krw_idx = krw_daily[b].index[krw_daily[b].index >= ref]
        usdt_idx = usdt_daily[usdt].index[usdt_daily[usdt].index >= ref]
        if len(krw_idx) > 0 and len(usdt_idx) > 0:
            common_start = max(krw_idx.min(), usdt_idx.min())
            common_end = min(krw_idx.max(), usdt_idx.max())
            common_period_daily[b] = {
                "start": str(common_start.date()),
                "end": str(common_end.date()),
                "n_days": len(set(krw_idx).intersection(set(usdt_idx))),
            }

    common_period_4h = {}
    for b in common_4h:
        usdt = KRW_TO_USDT[b]
        # KRW 4h를 UTC로 변환
        krw_4h_utc = krw_to_utc(krw_4h[b])
        usdt_4h_utc = usdt_4h[usdt]  # 이미 KST timezone
        # 둘 다 UTC로 통일 (USDT 4h는 KST → UTC 변환 필요)
        # usdt_4h index는 KST → UTC 변환
        usdt_4h_utc = usdt_4h[usdt].copy()
        # usdt_4h index is KST (tz-aware) -> convert to UTC
        if usdt_4h_utc.index.tz is not None:
            usdt_4h_utc.index = usdt_4h_utc.index.tz_convert("UTC")
        else:
            usdt_4h_utc.index = usdt_4h_utc.index.tz_localize("UTC")

        krw_idx = krw_4h_utc.index[krw_4h_utc.index >= ref_utc]
        usdt_idx = usdt_4h_utc.index[usdt_4h_utc.index >= ref_utc]
        if len(krw_idx) > 0 and len(usdt_idx) > 0:
            common_start = max(krw_idx.min(), usdt_idx.min())
            common_end = min(krw_idx.max(), usdt_idx.max())
            common_period_4h[b] = {
                "start": str(common_start.date()),
                "end": str(common_end.date()),
                "n_bars": len(set(krw_idx).intersection(set(usdt_idx))),
            }

    out["common_period_daily"] = common_period_daily
    out["common_period_4h"] = common_period_4h

    # 타임스탬프 정렬 검증 (샘플)
    out["alignment_check"] = {}
    for b in common_daily[:3]:
        usdt = KRW_TO_USDT[b]
        krw = krw_daily[b]
        usdt_d = usdt_daily[usdt]
        common_idx = krw.index.intersection(usdt_d.index)
        if len(common_idx) > 0:
            sample = common_idx[:3]
            out["alignment_check"][b] = {
                "sample_dates": [str(d.date()) for d in sample],
                "krw_close": krw.loc[sample, "close"].values.tolist(),
                "usdt_close": usdt_d.loc[sample].values.tolist(),
                "note": "KRW index=KST 00:00, USDT index=KST 24:00 (1일 시차)",
            }

    # Lead-lag 계산 가능 여부: 같은 시점 price series 확보 가능?
    out["lead_lag_feasibility"] = {
        "daily": {
            "possible": len(common_daily) >= 5,
            "symbols": common_daily,
            "alignment_issue": "KRW 00:00 vs USDT 24:00 = 1일 시차 → shift 필요",
        },
        "4h": {
            "possible": len(common_4h) >= 5,
            "symbols": common_4h,
            "alignment_issue": "KRW 4h UTC 변환 가능, USDT 1h→4h 리샘플 가능",
            "krw_4h_period": "2026-03-16~ (약 5.5개월만)",
        },
        "1h": {
            "possible": False,
            "reason": "KRW 1h 데이터 없음 (4h만 존재)",
        },
    }

    # JSON 저장
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, (np.generic, pd.Timestamp)):
            return str(obj)
        if isinstance(obj, dict):
            return {k: _to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [_to_jsonable(v) for v in obj]
        return str(obj)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(_to_jsonable(out), indent=2, ensure_ascii=False), encoding="utf-8")

    # 콘솔 요약
    print("=== Step 30 Exchange Lead-Lag Audit ===")
    print(f"\nKRW daily: {len(krw_daily)} symbols")
    print(f"KRW 4h: {len(krw_4h)} symbols (2026-03-16~)")
    print(f"USDT daily (from 1h): {len(usdt_daily)} symbols")
    print(f"USDT 4h (from 1h): {len(usdt_4h)} symbols")
    print(f"\nCommon daily symbols: {common_daily}")
    print(f"Common 4h symbols: {common_4h}")
    print("\nCommon period daily (2023-05-21~):")
    for b, v in common_period_daily.items():
        print(f"  {b:5s} {v['start']}~{v['end']} n={v['n_days']}")
    print("\nCommon period 4h:")
    for b, v in common_period_4h.items():
        print(f"  {b:5s} {v['start']}~{v['end']} n={v['n_bars']}")
    print("\nLead-lag feasibility:")
    for res, v in out["lead_lag_feasibility"].items():
        print(f"  {res}: possible={v['possible']} {'symbols='+str(v.get('symbols')) if v['possible'] else 'reason='+v.get('reason','')}")
        if "alignment_issue" in v:
            print(f"    alignment: {v['alignment_issue']}")
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()