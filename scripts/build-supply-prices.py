#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""공급망 지도용 주가 수익률 -> docs/data/supply-prices.json

대시보드 주가 데이터(sector-strength.json)는 관심종목 352개뿐이라, 공급망 지도에 나오는 그 밖의
상장사(한국 약 40곳 · 해외 약 25곳)는 수익률이 없다. 이 스크립트가 그 빈자리만 채운다.
  한국   네이버 일봉(fetch_macro.naver_daily, collect.js·테마 트리와 같은 출처)
  해외   Yahoo chart(fetch_macro.yahoo_daily) — 심볼은 config/supplyChain.json 노드의 "yahoo"
sector-strength 에 이미 있는 종목은 건너뛴다(화면이 그쪽을 먼저 쓴다). 기간은 sector-strength 와
같은 거래일 수: 1d=1 · 1w=5 · 1m=21 · 3m=63 · 6m=126.

★ 관찰용 맥락 자료다. 점수·매매 규칙에 쓰지 않는다(절대 규칙 1). 한 종목이 실패해도 나머지는 쓴다.

  python scripts/build-supply-prices.py
  python scripts/build-supply-prices.py --selftest
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
CONFIG = os.path.join(ROOT, "config", "supplyChain.json")
SECTOR = os.path.join(ROOT, "docs", "data", "sector-strength.json")
OUT = os.path.join(ROOT, "docs", "data", "supply-prices.json")
WINDOWS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "6m": 126}


def returns(closes):
    """종가 목록(오래된 것 먼저) -> {기간: 수익률}. 이력이 모자란 기간은 None."""
    last = closes[-1]
    return {k: (round(last / closes[-1 - n] - 1, 4) if len(closes) > n and closes[-1 - n] else None) for k, n in WINDOWS.items()}


def collect():
    from fetch_macro import naver_daily, yahoo_daily   # 지연 import — --selftest 는 네트워크 모듈이 필요 없다
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    have = {s["t"] for s in json.load(open(SECTOR, encoding="utf-8"))["stocks"]}
    prices, failed = {}, []
    for k, n in cfg["nodes"].items():
        if not n.get("listed") or k in have:
            continue
        try:
            if k.isdigit():
                rows, src = naver_daily(k, count=200), "naver"
            elif n.get("yahoo"):
                rows, src = yahoo_daily(n["yahoo"]), "yahoo"
            else:
                continue
            rows = sorted(rows)
            if len(rows) < 2:
                raise RuntimeError("행 부족")
            prices[k] = {"r": returns([c for _, c in rows]), "d": rows[-1][0], "src": src}
        except Exception as e:   # 상장폐지·심볼 오류 등 — 그 종목만 빠진다
            failed.append({"id": k, "name": n["name"], "err": str(e)[:80]})
        time.sleep(0.3)
    out = {"asOf": max((p["d"] for p in prices.values()), default=None), "prices": prices, "failed": failed}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"supply-prices: {len(prices)}종목 · 실패 {len(failed)} {[x['name'] for x in failed]}")


def selftest():
    c = [100.0 + i for i in range(200)]   # 매일 +1
    r = returns(c)
    assert r["1d"] == round(299 / 298 - 1, 4) and r["1w"] == round(299 / 294 - 1, 4) and r["6m"] == round(299 / 173 - 1, 4), r
    assert returns([100.0, 110.0])["1d"] == 0.1 and returns([100.0, 110.0])["1w"] is None   # 이력 부족은 None
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    miss = [k for k, n in cfg["nodes"].items() if n.get("foreign") and n.get("listed") and not n.get("yahoo")]
    assert not miss, f"yahoo 심볼 없는 해외 노드: {miss}"
    print("selftest OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else collect()
