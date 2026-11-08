#!/usr/bin/env python3
"""L2b: L2 에서 달러·금리·수급 칸이 사건 20건에 못 미쳐 시험 0건이었다(문턱이 2% 꼬리). 문턱을 완화한 새 사전등록.
문턱은 사건 건수(--count)만 보고 고른다 — 결과(수익률)는 보지 않았다."""
import json
from pathlib import Path

H = Path(__file__).parent
l2 = json.loads((H / "condition-grid-l2-config.json").read_text(encoding="utf-8"))
one = lambda n, s, o, v: dict(name=n, series=s, op=o, value=v)
f = [
    one("달러5일 +1%↑", "usd5", ">=", 0.01), one("달러5일 -1%↓", "usd5", "<=", -0.01), one("달러20일 +2%↑", "usd20", ">=", 0.02), one("달러20일 -2%↓", "usd20", "<=", -0.02),
    one("미10년금리5일 +0.15p↑", "tnx5", ">=", 0.15), one("미10년금리5일 -0.15p↓", "tnx5", "<=", -0.15), one("미10년금리20일 +0.3p↑", "tnx20", ">=", 0.3), one("미10년금리20일 -0.3p↓", "tnx20", "<=", -0.3),
    one("외국인5일 순매수 z≤-0.5", "frgn_z", "<=", -0.5), one("외국인5일 순매수 z≥+0.5", "frgn_z", ">=", 0.5), one("기관5일 순매수 z≤-0.5", "inst_z", "<=", -0.5), one("기관5일 순매수 z≥+0.5", "inst_z", ">=", 0.5),
    dict(name="VIX≥25∧달러5일 +1%↑", all=[dict(series="vix", op=">=", value=25), dict(series="usd5", op=">=", value=0.01)]),
    dict(name="VIX≥25∧금리5일 +0.15p↑", all=[dict(series="vix", op=">=", value=25), dict(series="tnx5", op=">=", value=0.15)]),
    dict(name="외국인 z≤-0.5∧RSI<30", all=[dict(series="frgn_z", op="<=", value=-0.5), dict(series="rsi14", op="<", value=30)]),
]
cfg = dict(l2, name="condition-grid-l2b", filters=f)
(H / "condition-grid-l2b-config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(f), "필터")
