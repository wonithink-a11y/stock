#!/usr/bin/env python3
"""L3 확증 설정 — 가설 하나: '미 10년 금리 20일 -0.3%p↓ 조건의 급락 사건 뒤 21일 초과수익은 양'을 L2 12곳에 없는 새 시장에서 확인.
사전등록 condition-grid-l3-preregistration-2026-11.md 와 한 쌍. 시장 목록은 결과·사건 건수를 보기 전에 고정한 것."""
import json
import sys
from pathlib import Path

H = Path(__file__).parent
MARKETS = [("호주ASX200", "^AXJO", 1), ("인도NIFTY", "^NSEI", 1), ("유로스톡스50", "^STOXX50E", 1), ("스페인IBEX", "^IBEX", 1), ("네덜란드AEX", "^AEX", 1), ("스위스SMI", "^SSMI", 1),
           ("캐나다TSX", "^GSPTSE", 0), ("브라질BOVESPA", "^BVSP", 0), ("신흥국EEM", "EEM", 0), ("선진국EFA", "EFA", 0)]
min_events = int(sys.argv[1]) if len(sys.argv) > 1 else 20
cfg = dict(name="condition-grid-l3", seed=20261108, nperm=1000, horizons=[5, 21, 63], primary=21, min_events=min_events, min_clusters=10, fdr=0.05, matched=True, l2=True,
           markets=[dict(name=n, ticker=t, vix_lag=l, flows=False) for n, t, l in MARKETS],
           events=[dict(name="DAILY(하루 -3%)", type="daily", thr=-0.03, gap=10), dict(name="R20(20일 -10%)", type="ret20", thr=-0.10, gap=10), dict(name="GAP(갭 -2%)", type="gap", thr=-0.02, gap=10)],
           filters=[dict(name="미10년금리20일 -0.3p↓", series="tnx20", op="<=", value=-0.3)])
(H / "condition-grid-l3-config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(cfg["markets"]), "시장", min_events, "건")
