#!/usr/bin/env python
"""Step 14A — Binance USDS-M Funding 연구 universe 확장.

기존 14+1 종목(BTC,ETH,SOL,XRP,ADA,DOGE,DOT,ATOM,AVAX,LINK,NEAR,OP,UNI,ARB)은
건드리지 않고, 새로 선정한 추가 종목만 같은 디렉터리에 수집한다.

- 저장 형식·manifest 스키마는 기존 build_crypto_funding_data.py와 동일하게 유지
- 최초 funding부터 2026-08-28 08:00 UTC까지 수집
- 8h grid·실제 interval·결측·중복 검증을 기존 analyze_series 방식으로 재사용
- manifest.json의 기존 symbols/extras는 두지 않고, 기존 파일을 읽어 병합하지 않음
  (Claude가 최종 병합) → 이 스크립트는 "신규 종목 manifest 조각"만 만든다.
"""
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_BASE = "https://fapi.binance.com"
HERE = Path(__file__).resolve().parent
FUNDING_DIR = HERE / "data" / "crypto" / "funding"

# Step 14A에서 추가로 선정된 종목 (실제 Binance 데이터 기반, 상장 6개월 이상, 8h funding grid)
NEW_TARGETS = [
    "BNB", "SUI", "1000PEPE", "WLD", "ZEC", "AAVE", "BCH", "LTC",
    "1000SHIB", "INJ", "TRX", "FIL", "XMR", "APT",
]

MAX_PAGE = 1000
PAGE_SLEEP = 0.15
MAX_RETRIES = 10
RETRY_BACKOFF = 1.0

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
    rows = []
    start_time = onboard_date_ms if onboard_date_ms is not None else 0
    while True:
        params = {"symbol": symbol, "limit": MAX_PAGE, "startTime": start_time}
        batch = get("/fapi/v1/fundingRate", params=params)
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

    diffs = df.index.to_series().diff().dropna().astype("timedelta64[s]").astype(int)
    diff_counts = Counter(diffs)
    mode_s, mode_n = diff_counts.most_common(1)[0]
    mode_h = mode_s // 3600

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
    print("Step 14A — new funding symbols collection:", datetime.now(timezone.utc).isoformat())
    print("=" * 70)

    exm = build_exchange_map()
    print(f"exchangeInfo: {len(exm)} perpetual symbols loaded")

    new_manifest = {
        "exchange": "Binance USDS-M",
        "source": API_BASE,
        "step": "14A",
        "collectedAtUtc": datetime.now(timezone.utc).isoformat(),
        "symbols": {},
    }
    issues = []

    for base in NEW_TARGETS:
        sym = f"{base}USDT"
        meta = exm.get(sym)
        print(f"\n[{base}] {sym}  status={meta['status'] if meta else 'NOT-IN-EXCHANGE'}"
              f"  onboard={meta['onboardDate'] if meta else None}")
        if meta is None or meta["status"] != "TRADING":
            issues.append(f"{sym}: NOT collectible — exchangeInfo status={meta['status'] if meta else 'missing'}")
            new_manifest["symbols"][sym] = {"base": base, "note": issues[-1], "exchangeInfo": meta}
            continue

        try:
            rows = fetch_funding_history(sym, meta.get("onboardDate_ms"))
        except Exception as e:
            issues.append(f"{sym}: fetch FAILED - {e}")
            new_manifest["symbols"][sym] = {"base": base, "note": "fetch failed", "error": str(e)}
            print(f"      FETCH FAILED: {e}")
            continue

        if not rows:
            issues.append(f"{sym}: API returned empty funding history")
            new_manifest["symbols"][sym] = {"base": base, "note": "empty history", "exchangeInfo": meta}
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

        new_manifest["symbols"][sym] = {"base": base, "exchangeInfo": meta}
        new_manifest["symbols"][sym].update(ana)

    new_manifest["apiIssuesWhileCollecting"] = issues

    out_path = FUNDING_DIR / "_manifest_step14a_new.json"
    out_path.write_text(json.dumps(new_manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print("\n" + "=" * 70)
    print(f"new-step manifest fragment written: {out_path}")
    print("issues:", issues if issues else "none")
    print("done.")

    print("\n--- Step 14A QA summary ---")
    for sym, d in new_manifest["symbols"].items():
        if "recordCount" not in d:
            continue
        print(f"{sym:12s} {d['firstTime']} -> {d['lastTime']}  n={d['recordCount']:6d}  "
              f"intv={d['observedIntervalHours']}h  missing={d['missingSlots']}  dup={d['duplicatesRemoved']}")


if __name__ == "__main__":
    main()
