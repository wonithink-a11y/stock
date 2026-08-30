#!/usr/bin/env python
"""Step 28 — Binance Liquidation Historical Data 감사.

Binance USDS-M 퍼페추얼 청산(Liquidation) 데이터가 2023-05-21~현재까지
장기 확보 가능한지 실측 감사.

- 대량 다운로드 금지, probe만 수행
- 418/429 발생 시 즉시 중단
- 기존 데이터/전략/findings 수정 금지
"""
import json
import time
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "liquidation-data-audit-2026-08.json"
OUT_MD = HERE / "findings" / "liquidation-data-audit-2026-08.md"

BASE = "https://fapi.binance.com"
UA = {"User-Agent": "Mozilla/5.0 (research data audit; python-requests)"}
PACE = 1.5  # 요청 간 최소 간격 (초)

# 테스트 대상 심볼 (28종목 중 대표 7개 + 나머지)
REP_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "NEARUSDT",
               "BNBUSDT", "1000PEPEUSDT"]
ALL28 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
         "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
         "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
         "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
         "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "ZECUSDT"]

# Binance liquidation endpoints
ENDPOINTS = {
    "forceOrders": "/fapi/v1/forceOrders",      # 강제 청산 주문 (실시간 스트림용)
    "liquidationOrders": "/fapi/v1/liquidationOrders",  # 청산 주문 내역
}

# 테스트 시간 경계 (ms)
TEST_TIMES = {
    "recent_7d": int((datetime.now(timezone.utc).timestamp() - 7*86400) * 1000),
    "recent_30d": int((datetime.now(timezone.utc).timestamp() - 30*86400) * 1000),
    "recent_60d": int((datetime.now(timezone.utc).timestamp() - 60*86400) * 1000),
    "2025_01_01": int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
    "2024_01_01": int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000),
    "2023_05_21": int(datetime(2023, 5, 21, tzinfo=timezone.utc).timestamp() * 1000),
}

ABORTED = {"aborted": False, "reason": None}
CALLS = 0


def iso(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None


def call(path, params):
    global CALLS
    if ABORTED["aborted"]:
        return {"error": "aborted"}
    CALLS += 1
    time.sleep(PACE + random.uniform(0, 0.3))
    try:
        r = requests.get(BASE + path, params=params, headers=UA, timeout=30)
    except Exception as e:
        return {"error": f"request_failed: {e}"}
    if r.status_code == 418:
        ABORTED["aborted"] = True
        ABORTED["reason"] = f"HTTP 418 banned: {r.text[:120]}"
        return {"error": "banned_418", "msg": r.text[:120]}
    if r.status_code == 429:
        return {"error": "throttled_429", "msg": r.text[:120]}
    if r.status_code != 200:
        return {"error": f"http_{r.status_code}", "msg": r.text[:120]}
    try:
        j = r.json()
    except Exception:
        return {"error": "bad_json", "msg": r.text[:120]}
    if isinstance(j, dict):
        code = j.get("code")
        if code == -1003 or code in (418, 429):
            ABORTED["aborted"] = True
            ABORTED["reason"] = f"200 body ban code={code}: {str(j)[:120]}"
            return {"error": "banned_200body", "msg": str(j)[:120]}
        return {"error": f"api_{code}", "msg": str(j)[:120]}
    return j


def probe_endpoint(name, path):
    """단일 엔드포인트 종합 프로브."""
    res = {"endpoint": path, "auth": "none (public Market Data)",
           "probes": {}, "symbol_coverage": {}, "field_check": {}}

    # 1) BTCUSDT 시간 경계 프로브
    for label, st in TEST_TIMES.items():
        out = call(path, {"symbol": "BTCUSDT", "startTime": st, "limit": 10})
        if isinstance(out, list):
            ts = [r.get("time") or r.get("T") for r in out if isinstance(r, dict)]
            res["probes"][label] = {
                "n": len(out),
                "first_ts": iso(min(ts)) if ts else None,
                "last_ts": iso(max(ts)) if ts else None,
                "fields": list(out[0].keys()) if out else [],
                "startTime_honored": (iso(min(ts)) == iso(st) or
                                      (ts and min(ts) >= st - 1000)) if ts else None,
            }
        else:
            res["probes"][label] = out
        if ABORTED["aborted"]:
            res["aborted"] = True
            return res

    # 2) 대표 종목 커버리지 (limit=1)
    for s in REP_SYMBOLS:
        out = call(path, {"symbol": s, "limit": 1})
        if isinstance(out, list) and out:
            res["symbol_coverage"][s] = "ok"
        else:
            res["symbol_coverage"][s] = out.get("error", "no_data")

    # 3) 나머지 21종목
    rest = [s for s in ALL28 if s not in REP_SYMBOLS]
    ok_rest = 0
    for s in rest:
        out = call(path, {"symbol": s, "limit": 1})
        if isinstance(out, list) and out:
            ok_rest += 1
            res["symbol_coverage"][s] = "ok"
        else:
            res["symbol_coverage"][s] = out.get("error", "no_data")
    res["coverage_summary"] = {
        "rep_ok": sum(1 for v in res["symbol_coverage"].values() if v == "ok" and v in REP_SYMBOLS),
        "total_ok": sum(1 for v in res["symbol_coverage"].values() if v == "ok"),
        "over28": ok_rest + sum(1 for s in REP_SYMBOLS if res["symbol_coverage"].get(s) == "ok")
    }

    # 4) 필드 구조 검증 (첫 번째 성공 응답에서)
    for s in REP_SYMBOLS:
        out = call(path, {"symbol": s, "limit": 1})
        if isinstance(out, list) and out:
            first = out[0]
            expected_fields = ["time", "T", "symbol", "side", "price", "quantity",
                               "averagePrice", "notional", "qty", "orderId"]
            found = list(first.keys())
            res["field_check"] = {
                "sample_fields": found,
                "has_liquidation_time": "time" in first or "T" in first,
                "has_symbol": "symbol" in first,
                "has_side": "side" in first,
                "has_price": "price" in first or "averagePrice" in first,
                "has_quantity": "quantity" in first or "qty" in first,
                "has_notional": "notional" in first,
                "has_long_short_info": "side" in first,  # side가 LONG/SHORT 의미
            }
            break

    # 5) limit 상한 테스트
    out = call(path, {"symbol": "BTCUSDT", "limit": 1000})
    res["limit_probe"] = {"n_returned": len(out)} if isinstance(out, list) else out

    # 6) 중복/정렬 확인 (첫 성공 응답에서)
    for s in REP_SYMBOLS:
        out = call(path, {"symbol": s, "limit": 100})
        if isinstance(out, list) and len(out) > 1:
            ts = [r.get("time") or r.get("T") for r in out if isinstance(r, dict)]
            if ts:
                res["ordering_check"] = {
                    "ascending": ts == sorted(ts),
                    "strictly_increasing": all(a < b for a, b in zip(ts, ts[1:])),
                    "duplicate_timestamps": len(ts) != len(set(ts)),
                }
            break

    return res


def main():
    main_res = {
        "design": {
            "purpose": "Binance USDS-M Futures Liquidation 데이터 2023-05-21~현재 장기 가용성 감사",
            "method": "실제 공개 API 호출(probe만), 1.5s 페이싱, 418/-1003 즉시 중단",
            "ref_join_day": "2023-05-21 (연구 결합 기준일)",
            "endpoints_tested": list(ENDPOINTS.values()),
        },
        "endpoints": {},
    }

    for name, path in ENDPOINTS.items():
        print(f"Probing {name} ({path})...")
        main_res["endpoints"][name] = probe_endpoint(name, path)
        if ABORTED["aborted"]:
            print(f"[ABORT] {name}: {ABORTED['reason']}")
            break

    main_res["ban_aborted"] = ABORTED
    main_res["calls_made"] = CALLS

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(main_res, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== Step 28 Liquidation Availability Audit ===")
    print("calls:", CALLS, "| aborted:", ABORTED)
    for name, r in main_res["endpoints"].items():
        if "aborted" in r:
            print(f"  {name}: ABORTED")
            continue
        probes = r.get("probes", {})
        cov = r.get("coverage_summary", {})
        print(f"  {name:20s} cov={cov.get('over28', 0)}/28")
        for label, p in probes.items():
            if isinstance(p, dict) and "n" in p:
                print(f"    {label:12s} n={p['n']:2d} first={p.get('first_ts')} last={p.get('last_ts')}")
            else:
                print(f"    {label:12s} ERROR: {p}")
        if "field_check" in r:
            fc = r["field_check"]
            print(f"    fields: {fc}")
        if "limit_probe" in r:
            print(f"    limit: {r['limit_probe']}")
        if "ordering_check" in r:
            print(f"    ordering: {r['ordering_check']}")

    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()