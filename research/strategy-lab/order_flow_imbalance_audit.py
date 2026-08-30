#!/usr/bin/env python
"""Step 34 — Order-Flow Imbalance Data Audit.

기존 activity 데이터와 Binance 공개 API에서 장기 order-flow imbalance 데이터
가용성을 감사한다. 대량 수집 금지, 기존 파일 수정 금지.
"""
import json
import time
import warnings
from pathlib import Path

import requests

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "order-flow-imbalance-audit-2026-08.json"
OUT_MD = HERE / "findings" / "order-flow-imbalance-audit-2026-08.md"

BASE = "https://fapi.binance.com"
UA = {"User-Agent": "Mozilla/5.0 (research data audit; python-requests)"}
PACE = 1.5

SYM28 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
         "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
         "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
         "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
         "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "ZECUSDT"]

ABORTED = {"aborted": False, "reason": None}
CALLS = 0


def call(path, params):
    global CALLS
    if ABORTED["aborted"]:
        return {"error": "aborted"}
    CALLS += 1
    time.sleep(1.5)
    try:
        r = requests.get(BASE + path, params=params, headers=UA, timeout=30)
    except Exception as e:
        return {"error": f"request_failed: {e}"}
    if r.status_code == 418:
        return {"error": "banned_418", "msg": r.text[:120]}
    if r.status_code == 429:
        return {"error": "throttled_429", "msg": r.text[:120]}
    if r.status_code != 200:
        return {"error": f"http_{r.status_code}", "msg": r.text[:120]}
    try:
        return r.json()
    except Exception:
        return {"error": "bad_json", "msg": r.text[:120]}


def audit_existing_activity():
    """기존 activity/ 데이터의 order-flow 필드 확인."""
    import pandas as pd
    results = {}
    for sym in SYM28[:7]:  # 대표 7개만 체크
        p = HERE / "data" / "crypto" / "activity" / f"{sym}_1h.parquet"
        if not p.exists():
            results[sym] = {"error": "file_not_found"}
            continue
        df = pd.read_parquet(p)
        cols = list(df.columns)
        has_taker_buy_base = "taker_buy_base_asset_volume" in cols
        has_taker_buy_quote = "taker_buy_quote_asset_volume" in cols
        has_volume = "volume" in cols
        has_quote_volume = "quote_asset_volume" in cols
        has_trades = "number_of_trades" in cols
        
        n_rows = len(df)
        date_min = str(df["time"].min()) if "time" in df.columns else None
        date_max = str(df["time"].max()) if "time" in df.columns else None
        
        # Sample imbalance calculation
        if has_taker_buy_quote and has_quote_volume and has_volume and has_taker_buy_base:
            tbq = df["taker_buy_quote_asset_volume"]
            qv = df["quote_asset_volume"]
            vb = df["volume"]
            tbb = df["taker_buy_base_asset_volume"]
            taker_buy_ratio_q = (tbq / qv).replace([float('inf'), -float('inf')], float('nan')).mean()
            taker_buy_ratio_b = (tbb / vb).replace([float('inf'), -float('inf')], float('nan')).mean()
            buy_vol_q = tbq.sum()
            sell_vol_q = (qv - tbq).sum()
            imbalance_q = (buy_vol_q - sell_vol_q) / qv.sum()
        else:
            taker_buy_ratio_q = taker_buy_ratio_b = imbalance_q = None
        
        results[sym] = {
            "rows": n_rows,
            "date_range": f"{date_min} ~ {date_max}",
            "columns": cols,
            "has_taker_buy_base": has_taker_buy_base,
            "has_taker_buy_quote": has_taker_buy_quote,
            "has_volume": has_volume,
            "has_quote_volume": has_quote_volume,
            "has_trades": has_trades,
            "taker_buy_ratio_q_mean": taker_buy_ratio_q,
            "taker_buy_ratio_b_mean": taker_buy_ratio_b,
            "total_imbalance_q": imbalance_q,
        }
    return results


def probe_binance_endpoints():
    """Binance 공개 API에서 order-flow 관련 엔드포인트 프로브."""
    endpoints = {
        "klines": "/fapi/v1/klines",  # taker buy vol 포함
        "takerlongshortRatio": "/futures/data/takerlongshortRatio",  # taker long/short ratio
        "globalLongShortAccountRatio": "/futures/data/globalLongShortAccountRatio",
        "topLongShortAccountRatio": "/futures/data/topLongShortAccountRatio",
        "topLongShortPositionRatio": "/futures/data/topLongShortPositionRatio",
    }
    
    results = {}
    for name, path in endpoints.items():
        print(f"  Probing {name} ({path})...")
        results[name] = {}
        # Test BTCUSDT recent 7d
        out = call(path, {"symbol": "BTCUSDT", "period": "1h", "limit": 10})
        if isinstance(out, list) and out:
            results[name]["status"] = "ok"
            results[name]["sample_fields"] = list(out[0].keys()) if out and isinstance(out[0], dict) else []
            results[name]["sample_count"] = len(out)
        else:
            results[name]["status"] = "error"
            results[name]["error"] = out.get("error", str(out)[:120])
        
        # Test historical depth (startTime 2023-01-01)
        if name == "klines":
            st = int(pd.Timestamp("2023-01-01").timestamp() * 1000)
            out = call(path, {"symbol": "BTCUSDT", "interval": "1h", "startTime": st, "limit": 3})
            if isinstance(out, list) and out:
                results[name]["historical_2023"] = "ok"
                results[name]["earliest_ts"] = out[0][0] if out else None
            else:
                results[name]["historical_2023"] = "error"
                results[name]["error"] = out.get("error", str(out)[:120])
        
        if ABORTED["aborted"]:
            break
    return results


def main():
    t_start = time.time()
    print("=== Step 34 Order-Flow Imbalance Data Audit ===")
    
    # 1. Existing activity data
    print("\n[1] Existing activity/ data audit...")
    activity_results = audit_existing_activity()
    for sym, r in activity_results.items():
        if "error" in r:
            print(f"  {sym}: ERROR - {r['error']}")
        else:
            print(f"  {sym}: rows={r['rows']}, range={r['date_range']}")
            print(f"    taker_buy_quote={r['has_taker_buy_quote']}, taker_buy_base={r['has_taker_buy_base']}")
            print(f"    taker_ratio_q={r.get('taker_buy_ratio_q_mean'):.4f}, imbalance_q={r.get('total_imbalance_q'):.4f}")
    
    # 2. Binance API probe
    print("\n[2] Binance API endpoint probe...")
    import pandas as pd
    api_results = probe_binance_endpoints()
    for name, r in api_results.items():
        print(f"  {name}: {r.get('status', 'unknown')}")
        if "sample_fields" in r:
            print(f"    fields: {r['sample_fields']}")
        if "historical_2023" in r:
            print(f"    historical_2023: {r['historical_2023']}")
    
    # Summary
    out = {
        "design": {
            "purpose": "Order-flow imbalance data availability audit",
            "existing_data": "activity/ 1h parquet (taker buy volumes)",
            "api_endpoints": "fapi/v1/klines, futures/data/takerlongshortRatio, etc.",
            "constraints": "No bulk download, no existing data modification",
        },
        "existing_activity": activity_results,
        "api_probe": api_results,
        "calls_made": CALLS,
        "aborted": ABORTED["aborted"],
    }
    
    # JSON save
    def _to_jsonable(obj):
        if obj is None or isinstance(obj, (str, int, float, bool)): return obj
        if isinstance(obj, (list, tuple, set)): return [_to_jsonable(v) for v in obj]
        if isinstance(obj, dict): return {k: _to_jsonable(v) for k, v in obj.items()}
        return str(obj)
    
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(_to_jsonable(out), indent=2, ensure_ascii=False), encoding="utf-8")
    
    print(f"\nTotal runtime: {time.time() - t_start:.1f}s")
    print("JSON:", OUT_JSON)


if __name__ == "__main__":
    import time
    import pandas as pd
    import numpy as np
    from pathlib import Path
    HERE = Path(__file__).resolve().parent
    OUT_JSON = HERE / "findings" / "order-flow-imbalance-audit-2026-08.json"
    OUT_MD = HERE / "findings" / "order-flow-imbalance-audit-2026-08.md"
    import sys
    sys.path.insert(0, str(HERE))
    main()