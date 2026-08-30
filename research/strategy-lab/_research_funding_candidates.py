#!/usr/bin/env python
"""Binance USDS-M 퍼페추얼 전체 유니버스에서 거래량 기반 펀딩 후보를 선정한다.

- exchangeInfo → 모든 PERPETUAL 심볼 + onboardDate
- /fapi/v1/ticker/24hr → 24h 거래량
- /fapi/v1/premiumIndex → 현재 funding rate (선택적)
- 기존 14+2 종목은 제외하고 나머지 중 상위 후보를 출력
"""
import json
import sys
import time
from datetime import datetime, timezone

import requests

# Windows console encoding fix
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_BASE = "https://fapi.binance.com"
SESSION = requests.Session()

# 기존 수집된 종목 (이건 건드리지 않음)
EXISTING = {
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
    "DOTUSDT", "ATOMUSDT", "AVAXUSDT", "LINKUSDT", "NEARUSDT", "OPUSDT",
    "UNIUSDT", "ARBUSDT",
}


def get(path, params=None):
    for attempt in range(8):
        try:
            r = SESSION.get(API_BASE + path, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429):
                wait = 2 ** attempt
                print(f"  rate-limited {r.status_code}; backoff {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        except requests.RequestException as e:
            wait = 2 ** attempt
            time.sleep(wait)
    raise RuntimeError("failed")


def ms_to_iso(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def main():
    # 1. exchangeInfo
    info = get("/fapi/v1/exchangeInfo")
    perpetuals = {}
    for s in info["symbols"]:
        if s.get("contractType") != "PERPETUAL":
            continue
        if s.get("quoteAsset") != "USDT":
            continue
        perpetuals[s["symbol"]] = {
            "baseAsset": s["baseAsset"],
            "status": s["status"],
            "onboardDate_ms": s.get("onboardDate"),
            "onboardDate": ms_to_iso(s.get("onboardDate")),
            "pair": s.get("pair"),
        }
    print(f"Total USDT perpetuals: {len(perpetuals)}")

    # 2. 24h volume
    tickers = get("/fapi/v1/ticker/24hr")
    vol_map = {}
    for t in tickers:
        sym = t["symbol"]
        if sym in perpetuals:
            vol_map[sym] = {
                "quoteVolume": float(t.get("quoteVolume", 0)),
                "volume": float(t.get("volume", 0)),
                "count": int(t.get("count", 0)),
                "lastPrice": float(t.get("lastPrice", 0)),
            }

    # 3. premiumIndex (현재 funding rate)
    try:
        premiums = get("/fapi/v1/premiumIndex")
        prem_map = {p["symbol"]: p for p in premiums}
    except Exception:
        prem_map = {}

    # 4. 기존 종목 제외, 나머지 거래량순 정렬
    candidates = []
    for sym, meta in perpetuals.items():
        if sym in EXISTING:
            continue
        vol = vol_map.get(sym, {})
        qv = vol.get("quoteVolume", 0)
        onboard = meta["onboardDate_ms"] or 0
        onboard_dt = datetime.fromtimestamp(onboard / 1000.0, tz=timezone.utc)

        # 최근 상장(30일 이내) 필터
        now = datetime.now(timezone.utc)
        days_listed = (now - onboard_dt).days

        candidates.append({
            "symbol": sym,
            "base": meta["baseAsset"],
            "status": meta["status"],
            "onboardDate": meta["onboardDate"],
            "daysListed": days_listed,
            "quoteVolume24h": qv,
            "volume24h": vol.get("volume", 0),
            "tradeCount24h": vol.get("count", 0),
            "lastPrice": vol.get("lastPrice", 0),
        })

    # 거래량순 정렬
    candidates.sort(key=lambda x: x["quoteVolume24h"], reverse=True)

    # 5. 출력 — 상위 60개 (최소 30일 이상 상장, TRADING 상태)
    print(f"\n{'='*110}")
    print(f"Top candidates (excluding {len(EXISTING)} existing, sorted by 24h quote volume)")
    print(f"{'='*110}")
    print(f"{'Rank':>4} {'Symbol':<14} {'Base':<8} {'OnboardDate':<28} {'Days':>5} "
          f"{'24h Vol(USDT)':>16} {'24h Trades':>12} {'Price':>12}")
    print("-" * 110)

    filtered = [c for c in candidates if c["daysListed"] >= 30 and c["status"] == "TRADING"]
    for i, c in enumerate(filtered[:60], 1):
        print(f"{i:>4} {c['symbol']:<14} {c['base']:<8} {c['onboardDate']:<28} {c['daysListed']:>5} "
              f"{c['quoteVolume24h']:>16,.0f} {c['tradeCount24h']:>12,} {c['lastPrice']:>12.4f}")

    # 6. 최근 상장 종목 (30일 이내)
    recent = [c for c in candidates if c["daysListed"] < 30 and c["status"] == "TRADING"]
    if recent:
        print(f"\n{'='*80}")
        print(f"Recently listed (<30 days) — NOT recommended for inclusion:")
        print(f"{'='*80}")
        for c in recent:
            print(f"  {c['symbol']:<14} onboard={c['onboardDate']}  days={c['daysListed']}  "
                  f"vol={c['quoteVolume24h']:>14,.0f}")

    # 7. 정지/비활성 종목
    inactive = [c for c in candidates if c["status"] != "TRADING"]
    if inactive:
        print(f"\nInactive/delisted symbols:")
        for c in inactive:
            print(f"  {c['symbol']:<14} status={c['status']}")

    # 8. JSON으로도 출력
    out = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalPerpetuals": len(perpetuals),
        "existingCount": len(EXISTING),
        "candidates": filtered[:60],
        "recentlyListed": recent,
    }
    out_path = "research/strategy-lab/data/crypto/funding/_candidate_research.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nCandidate data saved to: {out_path}")


if __name__ == "__main__":
    main()
