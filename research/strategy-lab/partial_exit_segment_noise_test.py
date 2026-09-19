#!/usr/bin/env python3
"""부분익절 "세그먼트가 잡음을 만든다" 가설 검정 — 무작위 부분표본 대조.

    python research/strategy-lab/partial_exit_segment_noise_test.py --k 100
    python research/strategy-lab/partial_exit_segment_noise_test.py --selftest

★ 결과를 보기 전에 커밋한다. 아래 사전 선언은 결과 뒤에 바꾸지 않는다.

가설(partial-exit-segment-sweep-2026-09 §7): "중형주만 뗀 세그먼트의 VALID 붕괴(0.2033→0.0906)는 규칙의
결함이 아니라, 거래 767건을 시가총액으로 쪼개 표본이 얇아지며 생긴 잡음이다."

검정: 규칙 R = +40%에서 50% 매도 + 잔여분 트레일링 3%(전략 pbr_value_v1, 기준선 = 전량 보유).
  통계량 Δ = Sharpe(R) − Sharpe(전량보유), 구간별(ALL/TRAIN/VALID/TEST), 같은 부분표본 안에서 잰다.
  관측 = 중형(N≈335)·소형(N≈276) 세그먼트의 Δ. 귀무 = **시가총액과 무관하게 같은 N 을 무작위로 뽑은**
  부분표본 K 개의 Δ 분포(비복원, 시드 고정).

사전 선언 판정 (주 통계량 = 중형 ΔVALID):
  p = 무작위 부분표본 Δ 중 |Δ − 평균| ≥ |관측 − 평균| 인 비율(양측, 무작위 평균 기준)
  - NOISE-CONSISTENT : p ≥ 0.10  — 관측이 "같은 N 을 아무렇게나 자른" 분산 안에 있다 → 가설 지지
  - SEGMENT-SPECIFIC : p < 0.05  — 시가총액 세그먼트가 무작위 슬라이스보다 유의하게 다르다 → 가설 기각
  - AMBIGUOUS        : 그 사이
  소형 ΔVALID·두 세그먼트의 ΔALL 은 같은 방식으로 보조 보고(판정에는 안 쓴다).
  전체(767건) Δ 도 기준점으로 함께 보고한다.
한계 선언: 무작위 부분표본은 규칙을 안 건드리고 표본만 바꾸므로 "표본 크기가 만드는 분산"만 잰다.
  세그먼트에 진짜 신호가 있으면 SEGMENT-SPECIFIC 으로 나온다. 채택 결론이 아니라 잡음 가설의 검정이다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RULE_TRIGGER, RULE_FRACTION, RULE_TRAIL = 0.40, 0.5, 0.03
SEED = 20260919
PERIODS = ("ALL", "TRAIN", "VALID", "TEST")


def deltas(measure, strategy, start, end, run) -> dict:
    """같은 표본에서 (R − 전량보유) Sharpe 를 구간별로."""
    base = measure(strategy, None, None, start, end, run)
    rule = measure(strategy, RULE_TRIGGER, RULE_FRACTION, start, end, run, trail_pct=RULE_TRAIL)

    def pick(r):
        seg = r["segments"]
        out = {"ALL": r["resultTable"]["sharpe"]}
        for k in ("TRAIN", "VALID", "TEST"):
            v = seg.get(k) if isinstance(seg, dict) else None
            out[k] = v.get("sharpe") if isinstance(v, dict) else v
        return out

    b, r = pick(base), pick(rule)
    return {p: (None if b[p] is None or r[p] is None else r[p] - b[p]) for p in PERIODS}


def two_sided_p(obs: float, rand: list[float]) -> float:
    x = np.array([v for v in rand if v is not None and np.isfinite(v)])
    if len(x) == 0:
        return float("nan")
    m = x.mean()
    return float(np.mean(np.abs(x - m) >= abs(obs - m)))


def verdict(p: float) -> str:
    if not np.isfinite(p):
        return "판정불가"
    return "NOISE-CONSISTENT" if p >= 0.10 else "SEGMENT-SPECIFIC" if p < 0.05 else "AMBIGUOUS"


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    rnd = list(np.linspace(-1, 1, 101))
    ck("분포 중앙의 관측은 p 가 크다", two_sided_p(0.0, rnd) > 0.9)
    ck("분포 밖의 관측은 p 가 작다", two_sided_p(5.0, rnd) < 0.02)
    ck("판정 경계", verdict(0.10) == "NOISE-CONSISTENT" and verdict(0.049) == "SEGMENT-SPECIFIC"
       and verdict(0.07) == "AMBIGUOUS")
    ck("NaN 은 판정불가", verdict(float("nan")) == "판정불가")
    print(f"\nselftest {4 - len(fails)}/4" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="pbr_value_v1")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-08-14")
    ap.add_argument("--k", type=int, default=100)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    from partial_exit_segment_sweep import load_shares, resolved_for_segment
    from partial_exit_sweep import load_run, measure

    t0 = time.time()
    run = load_run(a.strategy, a.start, a.end)
    shares = load_shares()
    allr = run["resolved"]
    print(f"거래 {len(allr)}건 ({time.time() - t0:.0f}s)", flush=True)

    res = {"rule": {"trigger": RULE_TRIGGER, "fraction": RULE_FRACTION, "trail": RULE_TRAIL},
           "k": a.k, "seed": SEED, "nTrades": len(allr)}
    res["full"] = deltas(measure, a.strategy, a.start, a.end, run)
    print("전체 Δ:", res["full"], flush=True)

    rng = np.random.default_rng(SEED)
    for seg in ("중형", "소형"):
        sub = resolved_for_segment(allr, "size", seg, shares, {})
        n = len(sub)
        obs = deltas(measure, a.strategy, a.start, a.end, dict(run, resolved=sub))
        print(f"[{seg}] N={n} 관측 Δ:", obs, flush=True)
        rand = {p: [] for p in PERIODS}
        for i in range(a.k):
            idx = np.sort(rng.choice(len(allr), size=n, replace=False))
            d = deltas(measure, a.strategy, a.start, a.end, dict(run, resolved=[allr[j] for j in idx]))
            for p in PERIODS:
                rand[p].append(d[p])
            if (i + 1) % 10 == 0:
                print(f"  {seg} {i + 1}/{a.k} ({time.time() - t0:.0f}s)", flush=True)
        stat = {}
        for p in PERIODS:
            x = np.array([v for v in rand[p] if v is not None], dtype=float)
            pv = two_sided_p(obs[p], rand[p]) if obs[p] is not None else float("nan")
            stat[p] = {"obs": obs[p], "randMean": float(x.mean()), "randSd": float(x.std(ddof=1)),
                       "randP05": float(np.percentile(x, 5)), "randP95": float(np.percentile(x, 95)),
                       "p": pv, "verdict": verdict(pv)}
        res[seg] = {"n": n, "stats": stat}
        print(f"[{seg}] ΔVALID: obs {obs['VALID']:+.4f}  무작위 평균 {stat['VALID']['randMean']:+.4f} "
              f"sd {stat['VALID']['randSd']:.4f}  p={stat['VALID']['p']:.3f} → {stat['VALID']['verdict']}", flush=True)

    out = os.path.join(HERE, "findings", "partial-exit-segment-noise-test-2026-09.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
    print(f"\n저장: {out} ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
