#!/usr/bin/env python
"""Step 21 — Futures Positioning(Long/Short Ratio) 데이터 가용성 감사.

Binance USDⓈ-M Futures 공개 Market Data API 4종을 실제 호출로 감사한다:
  1. /futures/data/globalLongShortAccountRatio
  2. /futures/data/topLongShortAccountRatio
  3. /futures/data/topLongShortPositionRatio
  4. /futures/data/takerlongshortRatio

원칙:
- 대량 다운로드 금지 — API probe/metadata만.
- 418(밴)·-1003 수신 즉시 전체 중단(Step 18 basis IP밴 경험 반영).
- 요청 간 최소 1.4s 페이싱, 재시도 스톰 없음, 총 호출 제한(약 66회).
- 미래 대량 확인은 경계 startTime probe(startTime 미지원/범위 밖 오류 코드 검출).
- 기존 funding/basis/OHLCV/S2/전략/findings 전부 수정하지 않는다.
출력: findings/positioning-data-audit-2026-08.json + MD.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "positioning-data-audit-2026-08.json"
OUT_MD = HERE / "findings" / "positioning-data-audit-2026-08.md"

BASE = "https://fapi.binance.com"
UA = {"User-Agent": "Mozilla/5.0 (research data audit; python-requests)"}
PACE = 1.4          # 요청 간 최소 간격 (초)
MAX_CALLS = 70
FUNDING_T0 = datetime(2019, 9, 1, tzinfo=timezone.utc)   # funding 원자료 시작 참조
KST_REF = datetime(2023, 5, 21, tzinfo=timezone.utc)     # 연구 결합 기준일

ENDPOINTS = {
    "globalLongShortAccountRatio": "/futures/data/globalLongShortAccountRatio",
    "topLongShortAccountRatio": "/futures/data/topLongShortAccountRatio",
    "topLongShortPositionRatio": "/futures/data/topLongShortPositionRatio",
    "takerlongshortRatio": "/futures/data/takerlongshortRatio",
}

REP_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "NEARUSDT",
               "BNBUSDT", "1000PEPEUSDT"]
ALL28 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
         "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
         "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
         "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
         "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "ZECUSDT"]

CALLS = 0
ABORTED = {"aborted": False, "reason": None}


def call(path, params):
    global CALLS
    if ABORTED["aborted"]:
        return {"error": "aborted"}
    CALLS += 1
    time.sleep(PACE)
    try:
        r = requests.get(BASE + path, params=params, headers=UA, timeout=30)
    except Exception as e:                                    # noqa: BLE001
        return {"error": f"request_failed: {e}"}
    ct = r.headers.get("content-type", "")
    if r.status_code == 418:
        ABORTED["aborted"] = True
        ABORTED["reason"] = (r.text[:160] + " | status=418")
        return {"error": "banned_418", "msg": r.text[:160]}
    if r.status_code == 429:
        return {"error": "throttled_429", "msg": r.text[:120]}
    if r.status_code != 200 or "json" not in ct:
        return {"error": f"http_{r.status_code}", "msg": r.text[:120]}
    try:
        j = r.json()
    except Exception:                                         # noqa: BLE001
        return {"error": "bad_json", "msg": r.text[:120]}
    if isinstance(j, dict):
        if j.get("code") == -1003 or j.get("code") in (418, 429):
            ABORTED["aborted"] = True
            ABORTED["reason"] = (str(j)[:160] + " | code=-1003 family")
            return {"error": "banned_200body", "msg": str(j)[:160]}
        if j.get("code") == -1130:
            return {"error": "startTime_out_of_range", "msg": str(j)[:120]}
        return {"error": f"api_{j.get('code')}", "msg": str(j)[:120]}
    return j


def iso(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except Exception:                                         # noqa: BLE001
        return None


def audit_endpoint(name, path):
    res = {"endpoint": path, "auth": "none (public Market Data)",
           "probes": {}, "symbol_coverage": {}}
    # --- A) BTC 구조적 probe (period=1d + 5m, startTime 경계) ---
    early_ts = []
    for label, period, st in [("p2023", "1d", "2023-05-01T00:00:00"),
                              ("p2021", "1d", "2021-01-01T00:00:00"),
                              ("p2019", "1d", "2019-09-01T00:00:00"),
                              ("p5m_refday", "5m", "2023-05-21T00:00:00")]:
        st_ms = int(datetime.fromisoformat(st).timestamp() * 1000)
        out = call(path, {"symbol": "BTCUSDT", "period": period,
                          "startTime": st_ms, "limit": 3})
        if isinstance(out, list):
            ts = [r.get("timestamp") for r in out if isinstance(r, dict)]
            res["probes"][label] = {
                "n": len(out), "returned_first": iso(min(ts)) if ts else None,
                "startTime_was": iso(st_ms), "fields": list(out[0].keys()) if out and isinstance(out[0], dict) else [],
                "startTime_honored": (iso(min(ts)) == iso(st_ms) or
                                      (ts and min(ts) >= st_ms - 1000)) if ts else None,
            }
            early_ts.extend(ts)
        else:
            res["probes"][label] = out
    # --- B) 대표 종목 커버리지 (7종목, period=4h, limit=1) ---
    for s in REP_SYMBOLS:
        out = call(path, {"symbol": s, "period": "4h", "limit": 1})
        if isinstance(out, list) and out:
            res["symbol_coverage"][s] = "ok"
            early_ts.append(out[0].get("timestamp"))
        else:
            res["symbol_coverage"][s] = out.get("error", "no_data")
    if ABORTED["aborted"]:
        res["aborted"] = True
        return res
    # --- C) 나머지 21종목 metadata probe (4h, limit=1) ---
    rest = [s for s in ALL28 if s not in REP_SYMBOLS]
    ok_rest = 0
    for s in rest:
        out = call(path, {"symbol": s, "period": "4h", "limit": 1})
        if isinstance(out, list) and out:
            ok_rest += 1
            early_ts.append(out[0].get("timestamp"))
            res["symbol_coverage"][s] = "ok"
        else:
            res["symbol_coverage"][s] = out.get("error", "no_data")
    res["coverage_summary"] = {"rep_ok": sum(1 for v in res["symbol_coverage"].values() if v == "ok"),
                               "total_ok": sum(1 for v in res["symbol_coverage"].values() if v == "ok"),
                               "over28": ok_rest + sum(1 for s in REP_SYMBOLS
                                                       if res["symbol_coverage"].get(s) == "ok")}
    # --- D) limit cap probe (global endpoint 전용 제한 참고, 여기서는 공통) ---
    if name == "globalLongShortAccountRatio":
        out = call(path, {"symbol": "BTCUSDT", "period": "5m", "limit": 1000})
        limit_out = {"n_returned": len(out)} if isinstance(out, list) else out
    else:
        limit_out = {"note": "limit cap은 docs(≤500) + 스킵(밴 방지)"}
    res["limit_cap_probe"] = limit_out
    # --- 요약 운항 ---
    ts_ok = [t for t in early_ts if isinstance(t, int)]
    res["observed"] = {
        "pacing_s": PACE,
        "min_returned_ts": iso(min(ts_ok)) if ts_ok else None,
        "has_pre2023": bool(ts_ok and min(ts_ok) < int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)),
        "has_pre20230521": bool(ts_ok and min(ts_ok) < int(KST_REF.timestamp() * 1000)),
    }
    return res


def retention_probe(name, path):
    """startTime 없이 대량 limit로 가장 오래된 사용 가능 시점(보유 깊이) 측정 + startTime 경계."""
    res = {}
    # 1) 심층: 1d limit1000 (BINANCE가 클램프하면 count < 1000로 드러남)
    for label, period, lim in [("depth_1d", "1d", 1000), ("depth_1h", "1h", 1000)]:
        out = call(path, {"symbol": "BTCUSDT", "period": period, "limit": lim})
        if isinstance(out, list) and out:
            ts = [r["timestamp"] for r in out if isinstance(r, dict)]
            res[label] = {"count": len(out),
                          "oldest": iso(min(ts)), "newest": iso(max(ts)),
                          "span_days": round((max(ts) - min(ts)) / 86400000, 2),
                          "ascending": ts == sorted(ts),
                          "strictly_increasing": all(a < b for a, b in zip(ts, ts[1:]))}
        else:
            res[label] = out
    # 2) 경계: startTime = now - X일 (period=1d limit=1) — -1130이면 범위 밖
    if name in ("globalLongShortAccountRatio", "takerlongshortRatio"):
        now_ms = int(time.time() * 1000)
        res["startTime_boundary"] = {}
        for days in [30, 60, 180, 365, 730, 1095]:
            st = now_ms - days * 86400000
            out = call(path, {"symbol": "BTCUSDT", "period": "1d",
                              "startTime": st, "limit": 1})
            if isinstance(out, list) and out:
                res["startTime_boundary"][f"now-{days}d"] = {"ok": True,
                                                             "returned": iso(out[0]["timestamp"])}
            else:
                res["startTime_boundary"][f"now-{days}d"] = {"ok": False, "err": out.get("error")}
    # 3) pagination: startTime+endTime 1일 윈도우 (한 번만, global 대표)
    if name == "globalLongShortAccountRatio":
        now_ms = int(time.time() * 1000)
        out = call(path, {"symbol": "BTCUSDT", "period": "1d",
                          "startTime": now_ms - 3 * 86400000,
                          "endTime": now_ms - 2 * 86400000, "limit": 5})
        res["pagination_window"] = ({"n": len(out),
                                     "rows": [iso(r["timestamp"]) for r in out]}
                                    if isinstance(out, list) else out)
    return res


def intervals_probe():
    """interval 지원 목록: BTC 1종목, 각 period limit=1 (endpoint당 1번, 최소)"""
    periods = ["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"]
    out = {}
    for name, path in ENDPOINTS.items():
        sup = []
        for p in periods:
            r = call(path, {"symbol": "BTCUSDT", "period": p, "limit": 1})
            if isinstance(r, list) and r:
                sup.append(p)
            if ABORTED["aborted"]:
                break
        out[name] = sup
    return out


def main():
    main_res = {
        "design": {
            "purpose": "Funding/Premium/Basis 이후 새 정보축 후보 — Futures Long/Short positioning 데이터 가용성 감사",
            "method": "실제 공개 API 호출(probe만, 대량 다운로드 없음), 1.4s 페이싱, 418/-1003 수신 시 전체 중단",
            "ref_start_funding": FUNDING_T0.isoformat(),
            "ref_join_day": KST_REF.strftime("%Y-%m-%d") + " (연구 결합 기준일 2023-05-21)",
        },
        "endpoints": {},
    }
    for name, path in ENDPOINTS.items():
        main_res["endpoints"][name] = audit_endpoint(name, path)
        if ABORTED["aborted"]:
            print("[ABORT] ban 감지:", ABORTED["reason"])
            break
        main_res["endpoints"][name]["retention"] = retention_probe(name, path)
        if ABORTED["aborted"]:
            print("[ABORT] ban 감지:", ABORTED["reason"])
            break
    if not ABORTED["aborted"]:
        main_res["intervals_supported"] = intervals_probe()

    main_res["ban_aborted"] = ABORTED
    main_res["calls_made"] = CALLS

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(main_res, indent=2, ensure_ascii=False), encoding="utf-8")
    print("=== Step 21 positioning availability audit ===")
    print("calls:", CALLS, "| aborted:", ABORTED)
    for name, r in main_res["endpoints"].items():
        if "aborted" in r:
            print(f"  {name:34s} ABORTED")
            continue
        obs = r.get("observed", {})
        cov = r["coverage_summary"]
        pr = r.get("probes", {})
        p2021 = pr.get("p2021", {})
        p2019 = pr.get("p2019", {})
        print(f"  {name:34s} cov={cov['over28']}/28  pre20230521={obs.get('has_pre20230521')} "
              f"min_ts={obs.get('min_returned_ts')}")
        print(f"      p2021: {str(p2021)[:90]}")
        print(f"      p2019: {str(p2019)[:90]}")
    if "intervals_supported" in main_res:
        print("  intervals:")
        for k, v in main_res["intervals_supported"].items():
            print(f"    {k:34s} {v}")
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()