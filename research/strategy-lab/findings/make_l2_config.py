#!/usr/bin/env python3
"""L2 조건 격자 설정 생성 — 사전등록(condition-grid-l2-preregistration-2026-11.md)과 한 쌍. 실행 전에 동결한다."""
import json
from pathlib import Path

H = Path(__file__).parent
base = json.loads((H / "streak-conditions-dense-config.json").read_text(encoding="utf-8"))


def rng(name, series, lo, hi):
    return dict(name=name, all=[dict(series=series, op=">=", value=lo), dict(series=series, op="<", value=hi)])


def one(name, series, op, v):
    return dict(name=name, series=series, op=op, value=v)


new_f = [
    one("달러5일 +2%↑", "usd5", ">=", 0.02), one("달러5일 -2%↓", "usd5", "<=", -0.02), one("달러20일 +4%↑", "usd20", ">=", 0.04), one("달러20일 -4%↓", "usd20", "<=", -0.04),
    one("미10년금리5일 +0.25p↑", "tnx5", ">=", 0.25), one("미10년금리5일 -0.25p↓", "tnx5", "<=", -0.25), one("미10년금리20일 +0.5p↑", "tnx20", ">=", 0.5), one("미10년금리20일 -0.5p↓", "tnx20", "<=", -0.5),
    one("FOMC 결정 3일 전", "fomc_next", "<=", 3), one("FOMC 직후 1일", "fomc_last", "<=", 1), dict(name="FOMC 사이(앞뒤 15일 밖)", all=[dict(series="fomc_next", op=">=", value=15), dict(series="fomc_last", op=">=", value=15)]),
    one("외국인5일 순매수 z≤-1", "frgn_z", "<=", -1), one("외국인5일 순매수 z≥+1", "frgn_z", ">=", 1), one("기관5일 순매수 z≤-1", "inst_z", "<=", -1), one("기관5일 순매수 z≥+1", "inst_z", ">=", 1),
    dict(name="VIX≥25∧달러5일 +2%↑", all=[dict(series="vix", op=">=", value=25), dict(series="usd5", op=">=", value=0.02)]),
    dict(name="VIX≥25∧금리5일 +0.25p↑", all=[dict(series="vix", op=">=", value=25), dict(series="tnx5", op=">=", value=0.25)]),
    dict(name="SMA200 아래∧FOMC 3일 전", all=[dict(series="sma200gap", op="<", value=0), dict(series="fomc_next", op="<=", value=3)]),
    dict(name="외국인 z≤-1∧RSI<30", all=[dict(series="frgn_z", op="<=", value=-1), dict(series="rsi14", op="<", value=30)]),
]
events = [
    dict(name="A(≥3일·-5%)", type="streak", L=3, D=0.05, gap=10),
    dict(name="DAILY(하루 -3%)", type="daily", thr=-0.03, gap=10),
    dict(name="R20(20일 -10%)", type="ret20", thr=-0.10, gap=10),
    dict(name="GAP(갭 -2%)", type="gap", thr=-0.02, gap=10),
]
mk = []
for m in base["markets"]:
    m = dict(m)
    m["flows"] = m["name"] in ("코스피", "코스닥")
    mk.append(m)
cfg = dict(name="condition-grid-l2", seed=20261108, nperm=1000, horizons=[5, 21, 63], primary=21, min_events=20, min_clusters=10, fdr=0.05, matched=True, l2=True,
           markets=mk, events=events, filters=base["filters"] + new_f)
(H / "condition-grid-l2-config.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
print(len(base["filters"]), "기존 +", len(new_f), "신규 =", len(cfg["filters"]), "필터")
