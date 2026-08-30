#!/usr/bin/env python
"""Step 29 — KRW/USDT Cross-Market Premium 감사.

기존 데이터만 활용해 Upbit KRW ↔ Binance USDT 상대가격/김치프리미엄
연구 가능성을 감사한다. 대량 수집 금지, 기존 파일 수정 금지.
"""
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "krw-usdt-premium-audit-2026-08.json"
OUT_MD = HERE / "findings" / "krw-usdt-premium-audit-2026-08.md"

# 종목 매핑
KRW_BASES = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "DOT", "ATOM", "AVAX",
             "LINK", "NEAR", "OP", "UNI", "ARB", "MATIC"]
USDT_28 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
           "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
           "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
           "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
           "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "ZECUSDT"]

KRW_TO_USDT = {b: f"{b}USDT" for b in KRW_BASES}


def load_krw_daily():
    """daily/ KRW 데이터 로드."""
    data = {}
    for b in KRW_BASES:
        p = HERE / "data" / "crypto" / "daily" / f"KRW-{b}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            data[b] = df
    return data


def load_usdt_activity():
    """activity/ USDT 1h 데이터에서 daily close 재구성."""
    # activity 데이터는 1h taker volume 등만 있음, close 없음
    # basis/1h 에 mark_close 존재 → 이를 KST daily close로 사용
    data = {}
    for s in USDT_28:
        p = HERE / "data" / "crypto" / "basis" / "1h" / f"{s}_1h.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            data[s] = df
    return data


def load_usdt_basis_8h():
    """basis/ 8h 데이터에서 close 확인."""
    data = {}
    for s in USDT_28:
        p = HERE / "data" / "crypto" / "basis" / f"{s}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            data[s] = df
    return data


def check_usdtkrw_rate():
    """USDT/KRW 환율 데이터 존재 여부 확인."""
    # 기존 데이터에 환율 있는지 확인
    candidates = [
        HERE / "data" / "crypto" / "usdtkrw.parquet",
        HERE / "data" / "fx" / "usdtkrw.parquet",
        HERE / "data" / "usdtkrw.parquet",
    ]
    for p in candidates:
        if p.exists():
            return p, pd.read_parquet(p)
    return None, None


def krw_to_kst_daily(krw_data):
    """KRW daily는 이미 KST daily (00:00 KST 경계)."""
    # 이미 date index KST naive daily
    return krw_data


def usdt_to_kst_daily(usdt_1h_data):
    """USDT 1h mark_close → KST daily close (24:00 KST = 15:00 UTC)."""
    if usdt_1h_data is None or len(usdt_1h_data) == 0:
        return None
    df = usdt_1h_data.copy()
    # time 컬럼이 UTC datetime
    df["kst_date"] = (df["time"] + pd.Timedelta(hours=9)).dt.tz_localize(None).dt.normalize()
    # KST 24:00(=UTC 15:00)에 마감되는 바 = 14:00 UTC 시작 바
    # 14:00 UTC = 23:00 KST, close 15:00 UTC = 24:00 KST
    df_14 = df[df["time"].dt.hour == 14]
    daily = df_14.groupby("kst_date")["mark_close"].last()
    daily.index.name = "date"
    return daily


def main():
    out = {"design": {
        "purpose": "기존 데이터만으로 KRW/USDT 크로스마켓 프리미엄 구축 가능성 감사",
        "formula": "KRW_premium = Upbit_KRW_price / (Binance_USDT_price × USDTKRW) - 1",
        "ref_date": "2023-05-21",
        "constraints": "대량 수집 금지, 기존 데이터만 사용, 추정 금지",
    }}

    # 1) KRW daily 로드
    krw_data = load_krw_daily()
    out["krw_coverage"] = {}
    for b, df in krw_data.items():
        if len(df) == 0:
            out["krw_coverage"][b] = {"rows": 0, "error": "empty"}
            continue
        # date index가 이미 KST daily
        dmin = df.index.min()
        dmax = df.index.max()
        out["krw_coverage"][b] = {
            "rows": int(len(df)),
            "start": str(dmin.date()) if hasattr(dmin, "date") else str(dmin),
            "end": str(dmax.date()) if hasattr(dmax, "date") else str(dmax),
            "has_close": "close" in df.columns,
        }

    # 2) USDT 1h (basis/1h) → KST daily close
    usdt_1h = load_usdt_activity()
    usdt_daily = {}
    out["usdt_coverage"] = {}
    for s, df in usdt_1h.items():
        if len(df) == 0:
            out["usdt_coverage"][s] = {"rows": 0}
            continue
        daily = usdt_to_kst_daily(df)
        if daily is not None and len(daily) > 0:
            usdt_daily[s] = daily
            dmin = daily.index.min()
            dmax = daily.index.max()
            out["usdt_coverage"][s] = {
                "rows": int(len(daily)),
                "start": str(dmin.date()) if hasattr(dmin, "date") else str(dmin),
                "end": str(dmax.date()) if hasattr(dmax, "date") else str(dmax),
            }
        else:
            out["usdt_coverage"][s] = {"rows": 0, "note": "no 14:00 UTC bars"}

    # 3) 공통 종목 (KRW 15개 중 USDT 28개에 있는 것)
    common_symbols = []
    for b in KRW_BASES:
        usdt = KRW_TO_USDT.get(b)
        if usdt in usdt_daily and b in krw_data:
            common_symbols.append(b)
    out["common_symbols"] = common_symbols

    # 4) 공통 기간 (2023-05-21~현재)
    ref_date = pd.Timestamp("2023-05-21")
    common_period = {}
    for b in common_symbols:
        krw = krw_data[b]
        usdt = usdt_daily[KRW_TO_USDT[b]]
        # 2023-05-21 이후 교집합
        krw_idx = krw.index[krw.index >= ref_date]
        usdt_idx = usdt.index[usdt.index >= ref_date]
        if len(krw_idx) == 0 or len(usdt_idx) == 0:
            common_period[b] = {"error": "no overlap after 2023-05-21"}
            continue
        common_start = max(krw_idx.min(), usdt_idx.min())
        common_end = min(krw_idx.max(), usdt_idx.max())
        common_period[b] = {
            "start": str(common_start.date()),
            "end": str(common_end.date()),
            "n_days": int(len(usdt_idx.intersection(krw_idx))) if hasattr(usdt_idx, "intersection") else int(len(set(krw_idx).intersection(set(usdt_idx)))),
        }
    out["common_period"] = common_period

    # 5) USDT/KRW 환율 데이터 확인
    fx_path, fx_data = check_usdtkrw_rate()
    out["fx_data"] = {"found": fx_path is not None, "path": str(fx_path) if fx_path else None}
    if fx_data is not None:
        out["fx_data"]["rows"] = len(fx_data)
        out["fx_data"]["columns"] = list(fx_data.columns)
        if hasattr(fx_data.index, "min"):
            out["fx_data"]["start"] = str(fx_data.index.min())
            out["fx_data"]["end"] = str(fx_data.index.max())

    # 6) 타임스탬프 정렬 검증 (샘플)
    out["alignment_check"] = {}
    for b in common_symbols[:3]:
        krw = krw_data[b]
        usdt = usdt_daily[KRW_TO_USDT[b]]
        common_idx = krw.index.intersection(usdt.index)
        if len(common_idx) > 0:
            sample = common_idx[:5]
            krw_vals = krw.loc[sample, "close"].values
            usdt_vals = usdt.loc[sample].values
            out["alignment_check"][b] = {
                "sample_dates": [str(d.date()) for d in sample],
                "krw_close": krw_vals.tolist(),
                "usdt_close_usd": usdt_vals.tolist(),
                "note": "KRW is KST 00:00 close, USDT is KST 24:00(=next 00:00) mark_close",
            }

    # 7) 프리미엄 계산 시뮬레이션 (환율 없이 USDT=KRW 1:1 가정 시)
    out["premium_sim_no_fx"] = {}
    for b in common_symbols[:3]:
        krw = krw_data[b]
        usdt = usdt_daily[KRW_TO_USDT[b]]
        common_idx = krw.index.intersection(usdt.index)
        common_idx = common_idx[common_idx >= ref_date]
        if len(common_idx) > 10:
            krw_c = krw.loc[common_idx, "close"]
            usdt_c = usdt.loc[common_idx]
            # USDT 가격에 환율 1 곱함 (USD≈KRW 가정) → 프리미엄 계산
            premium = krw_c / usdt_c - 1
            out["premium_sim_no_fx"][b] = {
                "n": len(premium),
                "mean": float(premium.mean()),
                "std": float(premium.std()),
                "min": float(premium.min()),
                "max": float(premium.max()),
                "note": "USDT/KRW=1 가정 시 계산된 프리미엄 (실제로는 환율 필요)",
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
    print("=== Step 29 KRW/USDT Premium Audit ===")
    print(f"\nKRW symbols: {len(krw_data)} (expected 15)")
    print(f"USDT daily (from 1h): {len(usdt_daily)}")
    print(f"Common symbols: {common_symbols}")
    print("\nKRW coverage (rows, start~end):")
    for b, v in out["krw_coverage"].items():
        print(f"  {b:5s} {v['rows']:4d} {v.get('start')}~{v.get('end')}")
    print("\nUSDT coverage (rows, start~end):")
    for s, v in out["usdt_coverage"].items():
        if v["rows"] > 0:
            print(f"  {s:14s} {v['rows']:4d} {v['start']}~{v['end']}")
    print("\nCommon period (2023-05-21~):")
    for b, v in common_period.items():
        print(f"  {b:5s} {v['start']}~{v['end']} n={v['n_days']}")
    print(f"\nFX data found: {out['fx_data']['found']} ({out['fx_data']['path']})")
    print("\nPremium sim (no FX, USD=KRW):")
    for b, v in out["premium_sim_no_fx"].items():
        print(f"  {b:5s} mean={v['mean']:+.4f} std={v['std']:.4f} n={v['n']}")
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()