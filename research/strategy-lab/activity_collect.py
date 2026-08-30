#!/usr/bin/env python
"""Step 23 — USDT 28서 Futures 거래활동 데이터 장기 수집 + QA.

소스: Binance USDS-M Futures 공개 API  GET /fapi/v1/klines (1h)
수집: volume, quote asset volume, number of trades,
      taker buy base asset volume, taker buy quote asset volume
기간: 각 종목 최초 bar ~ 2026-08-28 23:00 UTC (마지막 완전 1h bar)
저장: data/crypto/activity/{SYMBOL}_1h.parquet(+csv) + manifest.json

규칙: 기존 데이터(daily/4h/funding/basis/findings/S2/backtest) 수정 금지.
     /futures/data/* 가 아닌 /fapi/v1/klines 사용(Step 18 basis IP밴 계열 회피).
     저빈도 페이싱(1.2s), 418/-1003 수신 시 즉시 중단, 요청 스톰 금지.
     수집 + QA만 수행(분석/피처 생성/백테스트 금지).
"""
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "data" / "crypto" / "activity"

BASE = "https://fapi.binance.com"
PATH = "/fapi/v1/klines"
UA = {"User-Agent": "Mozilla/5.0 (research data collection; python-requests)"}
PACE = 1.2

# 표적 종료: 2026-08-28 마지막 완전 1h bar (openTime 23:00 UTC, close 08-29 00:00)
END_DT = datetime(2026, 8, 28, 23, 0, 0, tzinfo=timezone.utc)
END_MS = int(END_DT.timestamp() * 1000)

UNIVERSE28 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
              "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
              "UNIUSDT", "ARBUSDT", "1000PEPEUSDT", "1000SHIBUSDT", "AAVEUSDT",
              "APTUSDT", "BCHUSDT", "BNBUSDT", "FILUSDT", "INJUSDT", "LTCUSDT",
              "SUIUSDT", "TRXUSDT", "WLDUSDT", "XMRUSDT", "ZECUSDT"]

FIELDS = ["time", "open", "high", "low", "close", "volume", "close_time",
          "quote_asset_volume", "number_of_trades", "taker_buy_base_asset_volume",
          "taker_buy_quote_asset_volume", "_ignore"]

ABORT = {"stop": False, "reason": None}
CALLS = 0
RETRIES = {"n429": 0, "n418": 0}


def raw_get(symbol, start_time):
    global CALLS
    time.sleep(PACE + random.uniform(0, 0.3))
    while True:
        CALLS += 1
        try:
            r = requests.get(BASE + PATH, params={"symbol": symbol,
                                                  "interval": "1h",
                                                  "startTime": start_time,
                                                  "limit": 1000},
                             headers=UA, timeout=30)
        except Exception as e:                                     # noqa: BLE001
            raise RuntimeError(f"request_failed: {e}")
        if r.status_code == 418:
            RETRIES["n418"] += 1
            ABORT["stop"] = True
            ABORT["reason"] = f"HTTP418 banned: {r.text[:120]}"
            return None
        if r.status_code == 429:
            RETRIES["n429"] += 1
            if RETRIES["n429"] > 8:
                raise RuntimeError("429 recurrent — give up")
            time.sleep(25)
            continue
        if r.status_code != 200:
            raise RuntimeError(f"http_{r.status_code}: {r.text[:120]}")
        try:
            j = r.json()
        except Exception:                                          # noqa: BLE001
            raise RuntimeError(f"bad_json: {r.text[:120]}")
        if isinstance(j, dict):
            code = j.get("code")
            if code == -1003:
                RETRIES["n418"] += 1
                ABORT["stop"] = True
                ABORT["reason"] = f"200body ban -1003: {str(j)[:120]}"
                return None
            raise RuntimeError(f"api_{code}: {str(j)[:120]}")
        return j


def fetch_symbol(symbol):
    """startTime=0 부터 END_MS까지 연속 pagination. 최초 bar = 실제 상장 최초."""
    rows = []
    start = 0
    guard = 0
    while not ABORT["stop"]:
        guard += 1
        if guard > 1000:
            raise RuntimeError("pagination guard exceeded")
        j = raw_get(symbol, start)
        if j is None or not j:
            break
        last_ot = int(j[-1][0])
        for a in j:
            ot = int(a[0])
            row = a[:11]
            rows.append((ot, row))
        if last_ot >= END_MS:
            break
        start = last_ot + 3600000
    if ABORT["stop"]:
        return None
    # 중복 안전 제거 + 표적 종료 필터 + 정렬
    seen = {}
    for ot, row in rows:
        if ot <= END_MS:
            seen[ot] = row
    sorted_rows = [seen[k] for k in sorted(seen)]
    return sorted_rows


def qa(df):
    n = len(df)
    res = {"rows": n}
    if n == 0:
        return res
    ot = df["time"].astype("int64") // 10**6
    res["first_utc"] = datetime.fromtimestamp(ot.iloc[0] / 1000, tz=timezone.utc).isoformat()
    res["last_utc"] = datetime.fromtimestamp(ot.iloc[-1] / 1000, tz=timezone.utc).isoformat()
    # 1h 그리드 대비 missing: (END-first)/3600h +1 - rows - 내부 갭
    expected = (END_MS - int(ot.iloc[0])) // 3600000 + 1
    dt = ot.diff().dropna()
    internal_gaps = int((dt != 3600000).sum())
    res["expected_grid"] = expected
    res["internal_gap_bars"] = internal_gaps
    res["missing_bars"] = expected - n
    res["missing_pct"] = round(100.0 * (expected - n) / expected, 4)
    res["duplicates"] = int(ot.duplicated().sum())
    for c in ["volume", "quote_asset_volume", "number_of_trades",
              "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume"]:
        res[f"nan_{c}"] = int(df[c].isna().sum())
    res["nonpositive_volume"] = int((df["volume"] <= 0).sum())
    res["nonpositive_quote"] = int((df["quote_asset_volume"] <= 0).sum())
    res["nonpositive_trades"] = int((df["number_of_trades"] <= 0).sum())
    # taker 이상값: 매수 체결량이 총량 초과(라운딩 허용 1e-6)
    eps = 1e-6
    res["taker_base_gt_volume"] = int((df["taker_buy_base_asset_volume"] > df["volume"] + eps).sum())
    res["taker_quote_gt_quote"] = int((df["taker_buy_quote_asset_volume"] > df["quote_asset_volume"] + eps).sum())
    res["taker_negative"] = int(((df["taker_buy_base_asset_volume"] < 0) | (df["taker_buy_quote_asset_volume"] < 0)).sum())
    res["first_pre_20230521"] = bool(int(ot.iloc[0]) < int(datetime(2023, 5, 21, tzinfo=timezone.utc).timestamp() * 1000))
    return res


def valid_done(sym):
    """이미 END까지 완성된 종목은 재조회 없이 스킵(resume)."""
    p = OUT_DIR / f"{sym}_1h.parquet"
    if not p.exists():
        return False
    try:
        df = pd.read_parquet(p, columns=["time"])
        if len(df) == 0:
            return False
        last = pd.to_datetime(df["time"].max(), utc=True)
        return int(last.timestamp() * 1000) == END_MS
    except Exception:                                             # noqa: BLE001
        return False


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    per = {}
    stats = {"calls": 0, "n429": 0, "n418": 0, "pacing_s": PACE,
             "end_target_utc": END_DT.isoformat(), "resumed_symbols": 0}
    try:
        for i, sym in enumerate(UNIVERSE28, 1):
            if valid_done(sym):
                d = pd.read_parquet(OUT_DIR / f"{sym}_1h.parquet")
                q = qa(d)
                per[sym] = q
                stats["resumed_symbols"] += 1
                print(f"[{i}/28] {sym} ... (resume, skipped) rows={q['rows']}", flush=True)
                continue
            print(f"[{i}/28] {sym} ...", flush=True)
            rows = fetch_symbol(sym)
            if ABORT["stop"]:
                per[sym] = {"error": f"aborted: {ABORT['reason']}"}
                print("  ABORT:", ABORT["reason"], flush=True)
                break
            if rows is None:
                per[sym] = {"error": "no data"}
                continue
            df = pd.DataFrame(rows, dtype="float64")
            df.columns = (["ot", "open", "high", "low", "close", "volume", "ct",
                           "quote_asset_volume", "number_of_trades",
                           "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume"])
            df["time"] = pd.to_datetime(df["ot"], unit="ms", utc=True)
            df = df[["time", "volume", "quote_asset_volume", "number_of_trades",
                     "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume"]].copy()
            df["time"] = pd.to_datetime(df["time"], utc=True)
            q = qa(df)
            per[sym] = q
            if q["rows"]:
                df.to_parquet(OUT_DIR / f"{sym}_1h.parquet", index=False)
                df.to_csv(OUT_DIR / f"{sym}_1h.csv", index=False)
            print(f"  -> {q.get('rows')} rows | first={q.get('first_utc')} "
                  f"last={q.get('last_utc')} miss={q.get('missing_bars')} "
                  f"dup={q.get('duplicates')} pre2023={q.get('first_pre_20230521')}", flush=True)
    finally:
        stats["calls"] = CALLS
        stats["n429"] = RETRIES["n429"]
        stats["n418"] = RETRIES["n418"]

    # 요약: 28종목 성공, 2023-05-21 이전 존재, 공통 구간(funding/basis와)
    ok = {s: v for s, v in per.items() if isinstance(v, dict) and v.get("rows", 0) > 0}
    pre = {s: v for s, v in ok.items() if v.get("first_pre_20230521")}
    firsts = [datetime.fromisoformat(v["first_utc"]) for v in ok.values()]
    lasts = [datetime.fromisoformat(v["last_utc"]) for v in ok.values()]
    earliest_common_start = max(firsts) if firsts else None
    common_end = min(lasts) if lasts else None

    manifest = {
        "dataset": "activity_1h",
        "source": "Binance USDS-M Futures public market data /fapi/v1/klines (1h)",
        "generated": datetime.now(timezone.utc).isoformat(),
        "end_target_utc": END_DT.isoformat(),
        "resolution": "1h",
        "fields": ["time", "volume", "quote_asset_volume", "number_of_trades",
                   "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume"],
        "qa_summary": {
            "symbols_total": len(UNIVERSE28),
            "symbols_ok": len(ok),
            "symbols_err": sorted(set(UNIVERSE28) - set(ok)),
            "symbols_first_pre_20230521": len(pre),
            "earliest_common_start_all28": earliest_common_start.isoformat() if earliest_common_start else None,
            "common_end_all28": common_end.isoformat() if common_end else None,
            "research_window_start_utc": "2023-05-21T00:00:00+00:00",
            "overlap_with_research_window": bool(earliest_common_start and earliest_common_start <= datetime(2023, 5, 21, tzinfo=timezone.utc) and common_end and common_end >= datetime(2023, 5, 21, tzinfo=timezone.utc)),
        },
        "rate_limit_observed": stats,
        "per_symbol": per,
    }
    (OUT_DIR / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== Step 23 summary ===")
    print(f"calls={CALLS} 429={RETRIES['n429']} 418_ban_abort={ABORT['stop']} reason={ABORT['reason']}")
    print(f"resumed={stats['resumed_symbols']} symbols ok={len(ok)}/{len(UNIVERSE28)} "
          f"err={manifest['qa_summary']['symbols_err']}")
    print(f"first_pre_20230521={len(pre)}  earliest_common_start={earliest_common_start}")
    print("row counts (sorted):")
    for s in sorted(ok, key=lambda x: ok[x]["rows"]):
        v = ok[s]
        print(f"  {s:14s} rows={v['rows']:6d} first={v['first_utc'][:10]} "
              f"miss={v['missing_bars']:5d} dup={v['duplicates']} "
              f"vol_le0={v['nonpositive_volume']} trades_le0={v['nonpositive_trades']} "
              f"taker_anom={v['taker_base_gt_volume']}")

    # rate-limit/밴 조사 대상 의무 보고
    if ABORT["stop"]:
        print("\nRESULT: ABORTED due to ban — collection incomplete")
        sys.exit(2)
    print("\nRESULT: FINISHED")


if __name__ == "__main__":
    main()