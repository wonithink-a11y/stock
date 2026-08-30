#!/usr/bin/env python
"""Step 22 — Existing Crypto Data Feature Inventory.

현재 저장소(data/crypto/)에 이미 존재하는 Crypto 데이터의 실제 스키마와 coverage를 전수 감사한다.
새 데이터 수집 금지, API 호출 금지, 기존 파일 수정 금지. 오직 parquet 읽기만 수행.

분류:
  A = 이미 충분히 존재(추가 수집 불필요)
  B = 존재하나 품질/기간/coverage 확인 필요(후속 검증 후보)
  C = 현재 데이터에 없음(외부 소스 조사 후보)

출력: findings/crypto-feature-inventory-2026-08.json + MD.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "crypto"
OUT_JSON = HERE / "findings" / "crypto-feature-inventory-2026-08.json"
OUT_MD = HERE / "findings" / "crypto-feature-inventory-2026-08.md"

UNIVERSE28 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
              "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
              "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
              "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
              "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "ZECUSDT"]
KRW15 = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "DOT", "ATOM", "AVAX",
         "LINK", "NEAR", "OP", "UNI", "ARB", "MATIC"]


def read_df(path):
    """parquet를 읽고 datetime 축을 정규화. (컬럼만/메타로 끝내지 않고 필요 컬럼 통계용으로 읽음)"""
    df = pd.read_parquet(path)
    tcol = None
    dtypes = {}
    for c in df.columns:
        name = c.lower()
        if name in ("timestamp", "datetime", "time", "date", "open_time", "opentime"):
            tcol = c
        dtypes[c] = str(df[c].dtype)
    if isinstance(df.index, pd.DatetimeIndex):
        tmin, tmax, tname = df.index.min(), df.index.max(), f"index:{df.index.name}"
    elif tcol is not None:
        ser = pd.to_datetime(df[tcol])
        tmin, tmax, tname = ser.min(), ser.max(), f"col:{tcol}"
    else:
        tmin = tmax = None
        tname = "none"
    return df, {"tcol": tname, "tmin": tmin.isoformat() if tmin is not None else None,
                "tmax": tmax.isoformat() if tmax is not None else None, "dtypes": dtypes}


def null_rates(df):
    return {c: round(float(df[c].isna().mean()), 4) for c in df.columns}


def file_symbols(dir_path, suffix=""):
    out = {}
    for p in sorted(dir_path.glob(f"*{suffix}.parquet")):
        out[p.stem.replace(suffix, "")] = p
    return out


def audit_dir(sub, strip_suffix="", suffix=""):
    """symbol마다 독립 parquet인 디렉토리 감사."""
    d = DATA / sub
    if not d.is_dir():
        return None
    files = file_symbols(d, suffix)
    info = {"dir": str(d.relative_to(HERE)), "n_symbols": len(files),
            "files": sorted(str(f.relative_to(HERE)) for f in files.values())}
    per = {}
    agg = {}
    for sym, path in files.items():
        try:
            df, meta = read_df(path)
            per[sym] = {
                "rows": len(df), "tmin": meta["tmin"], "tmax": meta["tmax"],
                "nulls": null_rates(df),
            }
            for col in df.columns:
                agg.setdefault(col, {"dtype": str(df[col].dtype), "max_null": 0.0,
                                     "n_symbols_col": 0, "n_symbols_gap": 0})
                agg[col]["max_null"] = max(agg[col]["max_null"], null_rates(df)[col])
                agg[col]["n_symbols_col"] += 1 if null_rates(df)[col] < 1.0 else 0
                agg[col]["n_symbols_gap"] += 1 if null_rates(df)[col] > 0 else 0
        except Exception as e:     # noqa: BLE001
            per[sym] = {"error": str(e)}
    info["columns"] = {c: v for c, v in agg.items()}
    tmin_all = min((v["tmin"] for v in per.values() if isinstance(v, dict) and v.get("tmin")), default=None)
    tmax_all = max((v["tmax"] for v in per.values() if isinstance(v, dict) and v.get("tmax")), default=None)
    symbasis = {s.replace("KRW-", "") + "USDT" if s.startswith("KRW-") else s: s for s in files}
    matched = [b for b in UNIVERSE28 if b in symbasis]
    krw_matched = [b.replace("KRW-", "") for b in files if b.startswith("KRW-")]
    info.update({
        "per_symbol": per,
        "coverage": {"min": tmin_all, "max": tmax_all,
                     "matched_28_universe": len(matched),
                     "matched_28_list": matched,
                     "krw_bases": sorted(krw_matched)},
    })
    return info


def audit_funding():
    """funding 디렉토리: 8h. 28종목. field 스키마 + 결측."""
    return audit_dir("funding")


def audit_basis():
    d = DATA / "basis"
    res = {"8h": audit_dir("basis"), "1h": audit_dir("basis/1h", suffix="_1h")}
    mp = d / "manifest.json"
    try:
        res["manifest"] = json.loads(mp.read_text(encoding="utf-8"))
    except Exception:          # noqa: BLE001
        res["manifest"] = None
    return res


def main():
    inv = {
        "dataset": "crypto_feature_inventory",
        "generated": datetime.now(timezone.utc).isoformat(),
        "universe28": UNIVERSE28,
        "datasets": {
            "daily_krw": audit_dir("daily"),
            "4h_krw": audit_dir("4h"),
            "funding_8h": audit_funding(),
            "basis": audit_basis(),
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(inv, indent=2, ensure_ascii=False), encoding="utf-8")
    # 콘솔 요약
    print("rows/coverage per symbol (min) -> per dataset")
    for name, info in inv["datasets"].items():
        if isinstance(info, dict) and "per_symbol" in info:
            cov = info["coverage"]
            cols = " ".join(info["columns"].keys())
            print(f"[{name}] symbols={info['n_symbols']} 28match={cov['matched_28_universe']}"
                  f" range={cov['min']}~{cov['max']}")
            print(f"    cols({len(info['columns'])}): {cols}")
            for s, v in info["per_symbol"].items():
                if isinstance(v, dict) and "rows" in v:
                    print(f"      {s:14s} rows={v['rows']:6d} {v['tmin']} ~ {v['tmax']}")
        elif isinstance(info, dict):
            for sub, v in info.items():
                if isinstance(v, dict) and "per_symbol" in v:
                    cov = v["coverage"]
                    cols = " ".join(v["columns"].keys())
                    print(f"[{name}/{sub}] symbols={v['n_symbols']} 28match={cov['matched_28_universe']}"
                          f" range={cov['min']}~{cov['max']}")
                    print(f"    cols({len(v['columns'])}): {cols}")
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()