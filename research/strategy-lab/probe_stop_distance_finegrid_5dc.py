#!/usr/bin/env python
"""5DC-v1A-P 리스크 계약 스톱 배수 정밀 스윕 — 2026-08-21 probe_stop_distance_
candidates_5dc.py(C0~C4)의 후속. 사용자 지시(2026-08-21, "다음 작업은 Paper
Trading 스케줄러가 아니라 5DC-v1A-P 리스크 계약 정밀 스윕이다"):

  1  기존 검증 조건과 데이터/PIT/비용 조건을 그대로 유지 - 이 파일은
     probe_stop_distance_candidates_5dc.py의 run_one_candidate()·
     _schedule_portfolio()를 바이트 단위로 그대로 재사용한다(복붙, 로직 변경 0)
  2  STOP 배수 2.25x·2.75x·3.25x 추가 실행 (기존 2.0/2.5/3.0/FIXED_MEDIAN/
     CAP_P75 사이 성긴 격자를 좁힌다)
  7  기존 실험 결과(stop_distance_candidates_5dc.json)는 안 건드리고, 새
     결과는 별도 파일(stop_distance_finegrid_5dc.json)에 기록

RESEARCH ONLY. engine/*, policy.json, rule.py 전부 미변경. data/backfill/에
아무것도 안 쓴다.

  python probe_stop_distance_finegrid_5dc.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from probe_stop_distance_candidates_5dc import run_one_candidate  # noqa: E402

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import load_strategy  # noqa: E402


def _drop_suspension_rows(bars):
    return bars[~((bars["open"] == 0) & (bars["high"] == 0) & (bars["low"] == 0))]


def main():
    start, end = "2014-05-13", "2026-08-03"  # C0~C4와 동일 - 조건 고정
    repo_root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

    rule = load_strategy("5dc_v1a_p", repo_root)
    universe = UniverseProvider(repo_root=repo_root, include_delisted=False)
    calendar = TradingCalendar(repo_root=repo_root)

    t0 = time.time()
    a2a = A2aProvider(repo_root=repo_root, use_cache=True)
    tickers = {e.ticker for e in universe.entries if e.source == "A1A"}
    bars_raw = a2a.load(tickers, start, end, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    candidates = {
        "C5_2p25xATR": lambda row, atr_t: 2.25 * atr_t,
        "C6_2p75xATR": lambda row, atr_t: 2.75 * atr_t,
        "C7_3p25xATR": lambda row, atr_t: 3.25 * atr_t,
    }

    results = []
    for name, fn in candidates.items():
        r = run_one_candidate(name, fn, repo_root, start, end, rule, universe, bars_by_ticker, calendar)
        print(json.dumps(r, indent=2, default=str))
        results.append(r)

    out_dir = os.path.join(repo_root, "research", "strategy-lab", "reports",
                            "2026-08-21-risk-contract-fix-candidates")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "stop_distance_finegrid_5dc.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "2026-08-21 사용자 지시 - 배수 정밀 스윕(C0~C4 후속, "
                        "동일 조건: A1A_ONLY, 동일 기간·비용·PIT). "
                        "stop_distance_candidates_5dc.json은 미변경(별도 파일).",
            "universeMode": "A1A_ONLY", "period": f"{start} ~ {end}",
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
