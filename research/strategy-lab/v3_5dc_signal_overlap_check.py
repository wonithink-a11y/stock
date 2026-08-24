#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v3_bollinger_rsi vs 5dc_v1a_p - 신호 겹침 독립성 검토.

배경: `findings/video-strategies-2026-08/audit.md`가 V3(BB+RSI, 스모크
Sharpe 1.20)를 "엔진 통합 전 5DC와의 독립성 검토 필요"로 막아뒀다(같은
BB(20,2σ) 지표 계열, 2026-08-22부터 미착수). 둘의 트리거는 구조적으로
다르다:
  - V3: Low[t] < BB_lower(20,2)[t] AND RSI14[t] <= 30  (밴드 하단 이탈=바닥)
  - 5DC: Close[t] > BB_mid[t] AND CCI[t-1]<=-100 AND CCI[t]>-100  (중심선
    회복=반등 확인, 바닥보다 늦은 시점)

같은 되돌림 사건을 다른 시점에 잡는 것뿐이라면(V3=바닥, 5DC=반등 확인)
"독립적인 알파"가 아니라 "같은 사건의 다른 관측"일 수 있다 - 이 스크립트는
그 가설을 직접 측정한다. 신호(ticker,date) 집합만 필요하므로 전체
백테스트(Portfolio 실행) 없이 각 rule.py의 compute_features/generate_signals
을 그대로 재사용해 신호만 계산한다(엔진 무변경, 두 strategies/ 디렉터리
전부 무변경).

측정:
  1. 완전 동일일 겹침 - 같은 종목에서 두 신호가 정확히 같은 날 발화하는 빈도
  2. 근접 선후관계 - 5DC 신호 발화일 기준, 그 이전 N거래일(기본 20 - CCI/BB
     회복 주기와 맞춘 임의값 아님, 두 지표 다 20일 창을 쓰므로 그 창 길이를
     그대로 재사용) 안에 같은 종목의 V3 신호가 있었는지(=같은 되돌림의
     "바닥"을 V3가 먼저 잡았을 가능성)

  python v3_5dc_signal_overlap_check.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

import importlib.util as _ilu  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"
LOOKBACK_DAYS = 20  # BB/CCI 둘 다 20일 창 - 그 창 길이를 그대로 재사용(신규 임계값 아님)


def _load_rule(strategy_id):
    path = os.path.join(REPO_ROOT, "research", "strategy-lab", "strategies", strategy_id, "rule.py")
    spec = _ilu.spec_from_file_location("rule_" + strategy_id, path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def signal_set(rule_mod, bars_by_ticker):
    """{ticker: sorted list of signal date strings}"""
    out = {}
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        features = rule_mod.compute_features(bars)
        raw = rule_mod._raw_signal_series(features).fillna(False)
        dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in features.index[raw]]
        if dates:
            out[ticker] = sorted(dates)
    return out


def main():
    t0 = time.time()
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=False)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(universe.tickers, START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print("bars loaded: %d tickers (%.0fs)" % (len(bars_by_ticker), time.time() - t0))

    v3_rule = _load_rule("v3_bollinger_rsi")
    dc5_rule = _load_rule("5dc_v1a_p")

    v3_signals = signal_set(v3_rule, bars_by_ticker)
    dc5_signals = signal_set(dc5_rule, bars_by_ticker)
    n_v3 = sum(len(v) for v in v3_signals.values())
    n_5dc = sum(len(v) for v in dc5_signals.values())
    print("V3 신호 %d건(%d종목), 5DC 신호 %d건(%d종목) (%.0fs)"
          % (n_v3, len(v3_signals), n_5dc, len(dc5_signals), time.time() - t0))

    # 1. 완전 동일일 겹침
    v3_pairs = {(t, d) for t, ds in v3_signals.items() for d in ds}
    dc5_pairs = {(t, d) for t, ds in dc5_signals.items() for d in ds}
    exact_overlap = v3_pairs & dc5_pairs
    print("\n[완전 동일일 겹침] %d건 (V3의 %.2f%%, 5DC의 %.2f%%)"
          % (len(exact_overlap), len(exact_overlap) / n_v3 * 100 if n_v3 else 0,
             len(exact_overlap) / n_5dc * 100 if n_5dc else 0))

    # 2. 근접 선후관계 - 5DC 신호일 기준 이전 LOOKBACK_DAYS 거래일 안에 같은
    # 종목의 V3 신호가 있었는지. 거래일 인덱스는 종목별 bars.index로 계산.
    n_5dc_preceded_by_v3 = 0
    n_5dc_checked = 0
    for ticker, dc5_dates in dc5_signals.items():
        bars = bars_by_ticker.get(ticker)
        if bars is None or bars.empty:
            continue
        idx = bars.index.astype(str)
        pos = {d: i for i, d in enumerate(idx)}
        v3_dates_for_ticker = set(v3_signals.get(ticker, []))
        if not v3_dates_for_ticker:
            n_5dc_checked += len(dc5_dates)
            continue
        v3_positions = sorted(pos[d] for d in v3_dates_for_ticker if d in pos)
        for d in dc5_dates:
            if d not in pos:
                continue
            n_5dc_checked += 1
            p = pos[d]
            # 이전 LOOKBACK_DAYS 거래일 안에 v3 신호가 있었는지(과거만, 미래 제외)
            if any(p - LOOKBACK_DAYS <= vp < p for vp in v3_positions):
                n_5dc_preceded_by_v3 += 1

    print("\n[근접 선후관계] 5DC 신호 %d건 중 직전 %d거래일 안에 같은 종목 V3 신호가"
          " 있었던 경우: %d건(%.2f%%)"
          % (n_5dc_checked, LOOKBACK_DAYS, n_5dc_preceded_by_v3,
             n_5dc_preceded_by_v3 / n_5dc_checked * 100 if n_5dc_checked else 0))

    result = {
        "period": "%s ~ %s" % (START, END), "lookbackDays": LOOKBACK_DAYS,
        "v3SignalCount": n_v3, "v3TickerCount": len(v3_signals),
        "dc5SignalCount": n_5dc, "dc5TickerCount": len(dc5_signals),
        "exactSameDayOverlapCount": len(exact_overlap),
        "exactSameDayOverlapPctOfV3": round(len(exact_overlap) / n_v3 * 100, 2) if n_v3 else None,
        "exactSameDayOverlapPctOf5dc": round(len(exact_overlap) / n_5dc * 100, 2) if n_5dc else None,
        "dc5Checked": n_5dc_checked, "dc5PrecededByV3WithinLookback": n_5dc_preceded_by_v3,
        "dc5PrecededByV3Pct": round(n_5dc_preceded_by_v3 / n_5dc_checked * 100, 2) if n_5dc_checked else None,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-24-v3-5dc-signal-overlap")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "v3-5dc-signal-overlap.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": result},
                   f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
