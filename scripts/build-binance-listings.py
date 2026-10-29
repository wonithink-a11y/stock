#!/usr/bin/env python3
"""바이낸스 최근 신규 상장 목록 → docs/data/binance-listings.json (대시보드 크립토 > '최근 신규 상장' 경고 칸).

    python scripts/build-binance-listings.py                 # docs/data/binance-listings.json 갱신(Actions 가 커밋)
    python scripts/build-binance-listings.py --out /tmp/x.json
    python scripts/build-binance-listings.py --selftest

'신규 상장' 정의는 연구 findings/binance-listing-preregistration-2026-10.md(BL7)와 같다:
바이낸스에 처음 나타난 코인이 USDT 마켓으로 시작(다른 마켓 첫 일봉이 USDT 보다 빠르면 제외), 스테이블·레버리지 토큰 제외.
제외 목록은 research/strategy-lab/futures/binance_listing.py(7bba3b1)의 STABLE·LEV 를 옮겨 적은 것 — 그쪽이 정본.
맥락·경고 전용(절대 규칙 1) — 점수·매매에 쓰지 않는다. 공개 API(data-api.binance.vision), 키 없음.
첫 실행은 USDT 심볼마다 첫 일봉 1회(약 450회, 1~2분), 이후는 새 심볼만 — 첫 일봉 날짜는 캐시(firstDay)에 남긴다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data" / "binance-listings.json"
API = "https://data-api.binance.vision/api/v3"
WINDOW_DAYS = 30
OTHER_Q = ["BTC", "BNB", "BUSD", "FDUSD", "USDC", "TUSD", "EUR", "TRY"]
STABLE = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "PAX", "EUR", "GBP", "AUD", "USDS", "USDSB", "SUSD", "UST", "USTC", "PAXG", "AEUR", "EURI", "XUSD", "USD1", "BFUSD", "RLUSD"}
LEV = re.compile(r"(UP|DOWN|BULL|BEAR)$")
BACKTEST = {"events": 547, "years": "2018~2026", "bl7_mean_pct": -10.0, "lose_share_pct": 72,
            "note": "상장 다음 날 시가 → 7일 뒤, BTC 대비. 연구 BL7 ROBUST · 강건성 PASS 4/4 · 업비트 원화 가격 CONSISTENT. 평균이지 개별 코인 예측이 아니다."}


def eligible(base: str) -> bool:
    return base not in STABLE and not LEV.search(base)


def stock_like(base: str) -> bool:   # 토큰화 주식처럼 보이는 것(이름이 B 로 끝나는 주식 티커 모양) — run_binance_listing_forward.py 와 같은 규칙, 표시 구분 전용
    return base.endswith("B") and base[:-1].isalpha() and len(base) <= 6


def _get(path: str, **params):
    import requests
    for k in range(5):
        try:
            r = requests.get(f"{API}/{path}", params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                return None
        except Exception:
            pass
        time.sleep(2 ** k)
    raise RuntimeError(f"{path} 응답 없음")


def first_day(sym: str) -> str | None:
    k = _get("klines", symbol=sym, interval="1d", startTime=0, limit=1)
    return datetime.fromtimestamp(int(k[0][0]) / 1000, timezone.utc).strftime("%Y-%m-%d") if k else None


def build(symbols: list[dict], cache: dict, first_fn, today: datetime) -> tuple[list[dict], dict]:
    by_base: dict[str, list[dict]] = {}
    for s in symbols:
        by_base.setdefault(s["base"], []).append(s)
    cutoff = (today - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    out = []
    for b, xs in sorted(by_base.items()):
        usdt = next((x["sym"] for x in xs if x["quote"] == "USDT"), None)
        if not usdt or not eligible(b):
            continue
        if usdt not in cache:
            cache[usdt] = first_fn(usdt)
        L = cache[usdt]
        if not L or L < cutoff:
            continue
        others = []
        for x in xs:
            if x["quote"] in OTHER_Q:
                if x["sym"] not in cache:
                    cache[x["sym"]] = first_fn(x["sym"])
                if cache[x["sym"]]:
                    others.append(cache[x["sym"]])
        if any(o < L for o in others):
            continue
        out.append({"base": b, "sym": usdt, "L": L, "stockLike": stock_like(b)})
    return sorted(out, key=lambda e: e["L"], reverse=True), cache


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    out = Path(a.out)
    prev = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    info = _get("exchangeInfo", permissions="SPOT")
    if not info or "symbols" not in info:
        print("exchangeInfo 실패 — 파일을 쓰지 않는다", file=sys.stderr)
        return 1
    syms = [{"sym": s["symbol"], "base": s["baseAsset"], "quote": s["quoteAsset"]} for s in info["symbols"] if s.get("status") == "TRADING"]
    now = datetime.now(timezone.utc)
    cache = dict(prev.get("firstDay", {}))
    todo = [s["sym"] for s in syms if s["quote"] == "USDT" and eligible(s["base"]) and s["sym"] not in cache]
    if todo:   # 첫 실행은 ~450회(1회 ~0.9초) — 6개 동시로 받아 캐시를 채운다(가중치 2 × 450, 분당 한도 6,000 안)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(6) as ex:
            cache.update(zip(todo, ex.map(first_day, todo)))
    listings, cache = build(syms, cache, first_day, now)
    doc = {"updatedAt": now.isoformat(timespec="seconds"), "windowDays": WINDOW_DAYS, "backtest": BACKTEST,
           "listings": listings, "symbolsTrading": len(syms), "firstDay": dict(sorted(cache.items()))}
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(json.dumps({"listings": len(listings), "cached": len(cache), "recent": [f"{x['sym']} {x['L']}" for x in listings[:10]]}, ensure_ascii=False))
    return 0


def selftest():
    ok = 0
    assert not eligible("BTCUP") and not eligible("FDUSD") and eligible("PEPE"); ok += 1
    syms = [{"sym": "AAAUSDT", "base": "AAA", "quote": "USDT"}, {"sym": "AAABTC", "base": "AAA", "quote": "BTC"},
            {"sym": "BBBUSDT", "base": "BBB", "quote": "USDT"}, {"sym": "OLDUSDT", "base": "OLD", "quote": "USDT"},
            {"sym": "USDCUSDT", "base": "USDC", "quote": "USDT"}, {"sym": "CCCBNB", "base": "CCC", "quote": "BNB"}]
    fd = {"AAAUSDT": "2026-11-05", "AAABTC": "2026-11-01", "BBBUSDT": "2026-11-10", "OLDUSDT": "2020-01-01", "USDCUSDT": "2026-11-09"}
    calls = []
    fn = lambda s: (calls.append(s), fd.get(s))[1]  # noqa: E731
    lst, cache = build(syms, {}, fn, datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert [x["base"] for x in lst] == ["BBB"] and lst[0]["stockLike"] and not stock_like("PEPE"); ok += 1                       # AAA 는 BTC 먼저 · OLD 는 오래됨 · 스테이블 제외 · CCC 는 USDT 없음
    n = len(calls)
    build(syms, cache, fn, datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert len(calls) == n; ok += 1                                           # 캐시로 재호출 없음
    lst2, _ = build(syms, cache, fn, datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert lst2 == []; ok += 1                                                # 30일 지나면 목록에서 빠짐
    print(f"selftest {ok}/4 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
