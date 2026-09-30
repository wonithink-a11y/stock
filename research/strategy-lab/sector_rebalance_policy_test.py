#!/usr/bin/env python3
"""섹터 리밸런싱 정책 비교 — 실행 전 고정한 설계(2026-09-30).

    python research/strategy-lab/sector_rebalance_policy_test.py --selftest
    python research/strategy-lab/sector_rebalance_policy_test.py   # -> findings/sector-rebalance-policy-results-2026-09.json

질문: 섹터를 같은 비중으로 들고 갈 때 어떤 리밸런싱 방식이 가장 성과가 좋았나.
- 대상 2개: 미국 SPDR 9섹터(1999-01~2026-09, 월 총수익) · 한국 20그룹(2016-02~2026-07, 그룹 내 등가중 월수익, `pension_sector_bond_test.kr_returns`).
- 목표 비중: 등가중(섹터 수 분의 1). 정책 6개 고정: 안 함(drift) · 매월 · 분기 · 반기 · 연 1회 · 밴드(어느 섹터든 목표 비중의 ±25% 상대 이탈 시 전체 리밸런스).
- 비용: 거래된 금액의 편도 5bp(한국은 민감도로 20bp 도 함께 낸다). 기준선: 미국은 SPY(시가총액 비중), 한국은 없음.
- 지표: CAGR · 변동성 · 샤프(무위험 0 — 정책 간 비교용) · MDD · 연 회전율 · 정책 간 ΔSharpe(연 1회 대비) 12개월 블록 부트스트랩 95% 구간.
- 판정 규칙(결과 전): 어떤 정책도 ΔSharpe 구간이 0 을 벗어나지 않으면 "정책 간 차이 구분 불가"이고, 그때는 회전율(비용)이 낮은 정책을 권고 방향으로 적는다.
  구분되면 그 정책이 "가장 좋았다"고 쓴다. 정책·밴드 폭을 결과를 보고 바꾸지 않는다.
- 한계: 하나의 역사 경로, 한국 표본 126개월, 그룹 수익은 종목 등가중 근사(ETF 가 아님).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
from pension_sector_bond_test import mret, kr_returns  # noqa: E402

SECT = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
POLICIES = {"안 함": None, "매월": 1, "분기": 3, "반기": 6, "연 1회": 12, "밴드±25%": "band"}


def simulate(R: np.ndarray, policy, cost: float):
    T, N = R.shape
    tw = np.ones(N) / N
    w = np.zeros(N)
    out = np.zeros(T)
    turn = 0.0
    for t in range(T):
        do = t == 0
        if not do and policy == "band":
            do = bool((np.abs(w - tw) > 0.25 * tw).any())
        elif not do and isinstance(policy, int):
            do = t % policy == 0
        if do:
            tr = np.abs(tw - w).sum()
            c = cost * tr
            turn += tr if t else 0.0
            w = tw.copy()
        else:
            c = 0.0
        r = float((w * R[t]).sum())
        out[t] = r - c
        w = w * (1 + R[t]) / (1 + r)
    return out, turn


def sh(x):
    return float(x.mean() * 12 / (x.std() * math.sqrt(12)))


def summ(x):
    wl = np.cumprod(1 + x)
    dd = wl / np.maximum.accumulate(wl) - 1
    return dict(cagr=float(wl[-1] ** (12 / len(x)) - 1), vol=float(x.std() * math.sqrt(12)), sharpe=sh(x), mdd=float(dd.min()))


def boot(a, b, n=2000, block=12, seed=5):
    T = len(a)
    rng = np.random.default_rng(seed)
    nb = math.ceil(T / block)
    ds = []
    for _ in range(n):
        st = rng.integers(0, T, nb)
        ix = np.concatenate([(s + np.arange(block)) % T for s in st])[:T]
        ds.append(sh(a[ix]) - sh(b[ix]))
    return [float(np.quantile(ds, .025)), float(np.quantile(ds, .975))]


def block_run(R: pd.DataFrame, costs=(0.0005,)):
    res = {}
    for c in costs:
        sims = {name: simulate(R.values, pol, c) for name, pol in POLICIES.items()}
        base = sims["연 1회"][0]
        res[f"cost_{int(c*1e4)}bp"] = {name: dict(**summ(x), turnover_per_year=t / (len(x) / 12),
                                                    d_sharpe_vs_annual=(None if name == "연 1회" else sh(x) - sh(base)),
                                                    d_sharpe_ci=(None if name == "연 1회" else boot(x, base)))
                                       for name, (x, t) in sims.items()}
    return res


def run():
    Rus = pd.concat({s: mret(s) for s in SECT}, axis=1).dropna()["1999-01":]
    out = {"US": dict(n=len(Rus), first=str(Rus.index[0].date()), last=str(Rus.index[-1].date()), res=block_run(Rus))}
    spy = mret("SPY")["1999-01":]
    out["US"]["spy"] = summ(spy.values)
    Rkr = kr_returns()
    out["KR"] = dict(n=len(Rkr), groups=Rkr.shape[1], first=str(Rkr.index[0].date()), last=str(Rkr.index[-1].date()),
                     res=block_run(Rkr, costs=(0.0005, 0.0020)))
    p = LAB / "findings" / "sector-rebalance-policy-results-2026-09.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", p)


def selftest():
    R = np.zeros((36, 3))
    o, t = simulate(R, 12, 0.0005)
    assert abs(o[0] + 0.0005 * 1.0) < 1e-12 and np.allclose(o[1:], 0) and t == 0
    R2 = np.tile([0.02, 0.0, 0.0], (60, 1))
    o1, t1 = simulate(R2, 1, 0.0)
    o0, t0 = simulate(R2, None, 0.0)
    assert t1 > t0 == 0 and o1.sum() < o0.sum()          # 승자를 계속 덜어내면 수익이 낮다
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else run()
