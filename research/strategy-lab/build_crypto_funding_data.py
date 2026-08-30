#!/usr/bin/env python
"""Binance USDS-M Perpetual Funding Rate 전체 이력을 수집해 Parquet로 저장한다.

- 데이터 소스: Binance USDS-M(Futures) 공개 API
    - GET /fapi/v1/exchangeInfo      : 심볼 메타(onboardDate, status 등)
    - GET /fapi/v1/fundingRate       : 펀딩레이트 history (1회 최대 1000행)
- 시작 시각이 없는 파라미터이므로 onboardDate 또는 최초 기록부터 end까지 전진 페이지네이션
- 429/418/5xx 발생 시 exponential backoff 재시도
- 중복 record 제거(time 기준), timestamp는 UTC 기준(timezone-naive)으로 보존
- 심볼별 결측 구간·실제 funding interval을 데이터에서 판별해 manifest에 기록
- 기존 OHLCV(Upbit KRW) 데이터는 읽지도 수정하지도 않는다.
- 저장 경로: research/strategy-lab/data/crypto/funding/
"""
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

API_BASE = "https://fapi.binance.com"
HERE = Path(__file__).resolve().parent
FUNDING_DIR = HERE / "data" / "crypto" / "funding"

# 우선 대상 (13개)
TARGET_BASES = [
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE",
    "DOT", "ATOM", "AVAX", "LINK", "NEAR", "OP", "UNI",
]
# 계약 연속성/상장시점 이슈를 실제로 확인/기록만 하기 위한 추가 심볼
EXTRA_BASES = ["ARB", "MATIC"]

MAX_PAGE = 1000
PAGE_SLEEP = 0.15
MAX_RETRIES = 10
RETRY_BACKOFF = 1.0  # 초 단위 지수 백오프: 1,2,4,...초

SESSION = requests.Session()


def _ms_to_iso(ms):
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def get(path, params=None, tries=MAX_RETRIES):
    last = None
    for attempt in range(tries):
        try:
            r = SESSION.get(API_BASE + path, params=params, timeout=30)
            if r.status_code in (200, 201):
                return r.json()
            if r.status_code in (418, 429):
                wait = RETRY_BACKOFF * (2 ** attempt)
                print(f"      rate-limited {r.status_code}; backoff {wait:.0f}s")
                time.sleep(wait)
                continue
            if 500 <= r.status_code < 600:
                wait = RETRY_BACKOFF * (2 ** attempt)
                print(f"      server error {r.status_code}; backoff {wait:.0f}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        except requests.RequestException as e:
            last = e
            wait = RETRY_BACKOFF * (2 ** attempt)
            print(f"      request error: {e}; backoff {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError(f"failed after {MAX_RETRIES} tries: {last}")


def fetch_funding_history(symbol, onboard_date_ms=None):
    """onboardDate부터 전진 페이지네이션으로 전체 이력 수집.

    주의: Binance /fapi/v1/fundingRate는 startTime을 주지 않으면
    최신 ~limit건만 반환한다. 따라서 시작 시각을 반드시 지정한다.
    """
    rows = []
    # startTime 명시 없음 → 최신 레코드만 반환하는 함정 방지용 시작 시각
    start_time = onboard_date_ms
    if start_time is None:
        start_time = 0
    while True:
        params = {"symbol": symbol, "limit": MAX_PAGE, "startTime": start_time}
        batch = get("/fapi/v1/fundingRate", params=params)
        # 2026-08-28 09:00 UTC 이후(수집 시점 이후)는 없음 — startTime이 미래면 빈 응답
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < MAX_PAGE:
            break
        new_start = batch[-1]["fundingTime"] + 1
        if new_start <= start_time:
            raise RuntimeError("pagination progress guard triggered")
        start_time = new_start
        time.sleep(PAGE_SLEEP)
        # 안전 가드: 2019-09 이후 8h → ~20,000 행(20페이지). 이상이면 중단
        if len(rows) > 100_000:
            raise RuntimeError(f"implausible row count {len(rows)}; aborting")
    return rows


def build_exchange_map():
    info = get("/fapi/v1/exchangeInfo")
    mapping = {}
    for s in info.get("symbols", []):
        if s.get("contractType") != "PERPETUAL":
            continue
        mapping[s["symbol"]] = {
            "pair": s.get("pair"),
            "baseAsset": s.get("baseAsset"),
            "quoteAsset": s.get("quoteAsset"),
            "marginAsset": s.get("marginAsset"),
            "status": s.get("status"),
            "onboardDate_ms": s.get("onboardDate"),
            "onboardDate": _ms_to_iso(s.get("onboardDate")),
            "fundingIntervalHours_official": s.get("fundingIntervalHours"),
        }
    return mapping


def analyze_series(symbol, rows):
    """타임스탬프 시퀀스에서 interval·결측·중복을 판별한다."""
    df = pd.DataFrame(
        {
            "time": pd.to_datetime([r["fundingTime"] for r in rows], unit="ms", utc=True),
            "symbol": symbol,
            "fundingRate": pd.to_numeric([r["fundingRate"] for r in rows], errors="coerce"),
            "markPrice": pd.to_numeric([r.get("markPrice", "") for r in rows], errors="coerce"),
        }
    ).set_index("time")
    df = df[~df.index.duplicated(keep="last")].sort_index()

    n_dup_raw = len(rows) - len(df)

    # --- funding interval 관찰 ---
    diffs = df.index.to_series().diff().dropna().astype("timedelta64[s]").astype(int)
    diff_counts = Counter(diffs)
    mode_s, mode_n = diff_counts.most_common(1)[0]
    mode_h = mode_s // 3600

    # --- 결측 판정: Binance 타임스탬프는 경계에서 -1s~+ms 지터가 있으므로
    # 경계에 "가장 가까운" 8h 슬롯으로 매핑한다. (t+4h)를 8h로 floor한 값.
    slot = (df.index + pd.Timedelta(hours=4)).floor("8h")
    jitter_mask = slot != df.index
    per_slot = slot.value_counts()
    max_per_slot = int(per_slot.max())
    double_slots = int((per_slot > 1).sum())

    expected = pd.date_range(slot.min(), slot.max(), freq=f"{mode_h}h", tz="UTC")
    covered = set(slot)
    missing = [t for t in expected if t not in covered]
    missing_n = len(missing)
    ranges = []
    if missing:
        miss_sorted = sorted(missing)
        start = prev = miss_sorted[0]
        for t in miss_sorted[1:]:
            if t == prev + pd.Timedelta(hours=mode_h):
                prev = t
            else:
                ranges.append((start, prev))
                start = prev = t
        ranges.append((start, prev))

    return {
        "recordCount": len(df),
        "duplicatesRemoved": n_dup_raw,
        "firstTime": df.index[0].isoformat(),
        "lastTime": df.index[-1].isoformat(),
        "firstTimeUtcMs": int(df.index[0].timestamp() * 1000),
        "lastTimeUtcMs": int(df.index[-1].timestamp() * 1000),
        "observedIntervalS": int(mode_s),
        "observedIntervalHours": mode_h,
        "intervalHistogramTop": diff_counts.most_common(5),
        "timestampJitterCount": int(jitter_mask.sum()),
        "timestampJitterMaxSeconds": 0 if jitter_mask.sum() == 0 else int(
            abs(df.index[jitter_mask] - slot[jitter_mask]).max().total_seconds()),
        "slotsWithMultipleRecords": int(double_slots),
        "maxRecordsInSlot": max_per_slot,
        "expectedSlots": int(len(expected)),
        "missingSlots": missing_n,
        "missingRanges": [
            {"start": a.isoformat(), "end": b.isoformat(), "slots": int(
                int((b - a).total_seconds() // (mode_h * 3600)) + 1)}
            for a, b in ranges
        ],
        "minFundingRate": float(df["fundingRate"].min()),
        "maxFundingRate": float(df["fundingRate"].max()),
        "series": df,
    }


def main():
    FUNDING_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 70)
    print("Binance USDS-M Funding Rate collection started:", datetime.now(timezone.utc).isoformat())
    print("=" * 70)

    exm = build_exchange_map()
    print(f"exchangeInfo: {len(exm)} perpetual symbols loaded")

    manifest = {"exchange": "Binance USDS-M", "source": API_BASE,
                "collectedAtUtc": datetime.now(timezone.utc).isoformat(),
                "symbols": {}, "extras": {}}

    issues = []
    all_bases = TARGET_BASES + EXTRA_BASES
    for base in all_bases:
        sym = f"{base}USDT"
        meta = exm.get(sym)
        print(f"\n[{base}] {sym}  status={meta['status'] if meta else 'NOT-IN-EXCHANGE'}"
              f"  onboard={meta['onboardDate'] if meta else None}")
        if meta is None or meta["status"] != "TRADING":
            issues.append(
                f"{sym}: NOT collectible — exchangeInfo status={meta['status'] if meta else 'missing'}. "
                f"(MATIC→POL 등 계약 전환/상장 이슈 기록)")
            manifest["extras"][sym] = {"note": issues[-1], "exchangeInfo": meta}
            continue

        try:
            rows = fetch_funding_history(sym, meta.get("onboardDate_ms"))
        except Exception as e:
            issues.append(f"{sym}: fetch FAILED - {e}")
            manifest["extras"][sym] = {"note": "fetch failed", "error": str(e)}
            print(f"      FETCH FAILED: {e}")
            continue

        if not rows:
            issues.append(f"{sym}: API returned empty funding history")
            manifest["extras"][sym] = {"note": "empty history", "exchangeInfo": meta}
            print("      empty history")
            continue

        try:
            ana = analyze_series(sym, rows)
        except Exception as e:
            issues.append(f"{sym}: analysis FAILED - {e}")
            print(f"      ANALYSIS FAILED: {e}")
            continue

        df = ana.pop("series")
        out_path = FUNDING_DIR / f"{sym}.parquet"
        df.to_parquet(out_path)
        df_table = df.reset_index()
        df_table.to_csv(FUNDING_DIR / f"{sym}.csv", index=False)
        print(f"      saved {len(df)} records "
              f"{df.index[0].isoformat()} ~ {df.index[-1].isoformat()} "
              f"(interval={ana['observedIntervalHours']}h, missing={ana['missingSlots']})")

        section = manifest["symbols"] if base in TARGET_BASES else manifest["extras"]
        section[sym] = {"base": base, "exchangeInfo": meta}
        section[sym].update(ana)
        if base in EXTRA_BASES and base == "ARB":
            section[sym]["note"] = "ARB: 퍼페추얼 상장 2023-03경 — OHLCV(2023-05-21~)와 join 가능하나 사전 padding 없음"
        if base in EXTRA_BASES and base == "MATIC":
            section[sym]["note"] = "MATIC: POL 전환(2024) 관련 계약 연속성 이슈"

    manifest["apiIssuesWhileCollecting"] = issues

    manifest_path = FUNDING_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print("\n" + "=" * 70)
    print(f"manifest written: {manifest_path}")
    print("issues:", issues if issues else "none")
    print("done.")

    # QA 요약 (2023-05-21 이전 존재 여부 등)
    print("\n--- QA summary ---")
    ohlcv_start = pd.Timestamp("2023-05-21", tz="UTC")
    ohlcv_end = pd.Timestamp("2026-08-27", tz="UTC")
    for sym, d in manifest["symbols"].items():
        pre = "YES" if d["firstTimeUtcMs"] < int(ohlcv_start.timestamp() * 1000) else "NO"
        print(f"{sym:10s} {d['firstTime']} -> {d['lastTime']}  n={d['recordCount']:6d}  "
              f"intv={d['observedIntervalHours']}h  missing={d['missingSlots']}  pre-2023-05: {pre}")


if __name__ == "__main__":
    main()