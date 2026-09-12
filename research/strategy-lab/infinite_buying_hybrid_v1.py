#!/usr/bin/env python3
"""V4.0 매수 + '후반전 매도비중 확대' 하이브리드 — 버전 조합 실험 1호.

    python research/strategy-lab/infinite_buying_hybrid_v1.py --selftest
    python research/strategy-lab/infinite_buying_hybrid_v1.py --rules <파일> --ticker TQQQ

가설 출처: 버전별 백테스트(세션인수인계-2026-09-12-b)에서 V2.1이 전체기간·2022위기·
2023회복·최근1년 네 구간 전부에서 TQQQ 최저 MDD를 냈다. V2.0/V2.1/V2.2/V3.0/V4.0의
매도 로직을 대조하면 공통점 하나가 갈린다 — V2.1만 후반전(사이클 절반 경과 후)에
"평단가(0% 수익) 즉시청산" 3번째 티어를 추가로 둔다. 나머지 전부(V4.0 포함)는 후반에도
잔여 물량 대부분이 고정 익절가를 무기한 기다린다 — 이게 급락 후 물량이 갇혀 MDD가
커지는 원인일 가능성이 있다.

이 파일은 V2.1의 정확한 티어 비율·문턱값을 그대로 베끼지 않는다(라오어 원저작물 재배포
금지, CLAUDE.md 규칙 5). 대신 "후반전에 매도 비중을 키운다"는 메커니즘만 가져와 V4.0의
연속 T 모델에 맞게 재구현한다 — quarter_frac 을 T=splits/2 이후 선형으로 키워, V4.0이
이미 갖고 있던 star_price(T에 따라 하락)의 적용 범위를 넓힌다. 매수 로직·나머지 매도
로직은 V4.0 그대로(plan_orders 재사용, 코드 중복 없음).
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from infinite_buying_engine import Rules, backtest, plan_orders, selftest as _v4_selftest


def dynamic_quarter_frac(t: float, r: Rules, max_frac: float) -> float:
    """T<=splits/2 이면 그대로. 그 뒤로 quarter_frac -> max_frac 선형 증가."""
    half = r.splits / 2
    if half <= 0 or t <= half:
        return r.quarter_frac
    growth = min(1.0, (t - half) / half)
    return r.quarter_frac + (max_frac - r.quarter_frac) * growth


def make_plan_fn(max_frac: float):
    def plan_fn(s, r, recent_closes):
        frac = dynamic_quarter_frac(s.t, r, max_frac)
        return plan_orders(s, replace(r, quarter_frac=frac), recent_closes)
    return plan_fn


def selftest() -> int:
    fails: list[str] = []

    def ck(name: str, cond: bool) -> None:
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    r = Rules(ticker="X", splits=40, base_pct=15.0, tick=0.01, star_slope=2.0,
              quarter_frac=0.25, reverse_enter_t=1.0, reverse_sell_div=2.0,
              reverse_buy_frac=0.25, reverse_star_window=5, seed=1000.0)

    ck("전반전(T<=N/2)은 quarter_frac 그대로", dynamic_quarter_frac(10.0, r, 0.75) == 0.25)
    ck("정확히 절반에서도 그대로(경계 포함)", dynamic_quarter_frac(20.0, r, 0.75) == 0.25)
    f30 = dynamic_quarter_frac(30.0, r, 0.75)
    ck("후반전 중간에서 quarter_frac < f < max_frac", 0.25 < f30 < 0.75)
    ck("완전 소진 문턱(T=splits)에서 max_frac", dynamic_quarter_frac(40.0, r, 0.75) == 0.75)
    ck("문턱 넘어도 max_frac 을 안 넘는다(과소진 clamp)",
       dynamic_quarter_frac(60.0, r, 0.75) == 0.75)
    ck("단조증가", dynamic_quarter_frac(25.0, r, 0.75) < dynamic_quarter_frac(35.0, r, 0.75))

    # V4.0 엔진 자체가 깨지지 않았는지(원본 selftest 그대로 재사용, 회귀)
    print()
    v4_ok = _v4_selftest() == 0
    ck("V4.0 원본 엔진 selftest 통과(회귀 없음 확인)", v4_ok)

    total = 7
    print(f"\nhybrid selftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--rules", type=Path)
    ap.add_argument("--ticker", default="TQQQ")
    ap.add_argument("--splits", type=int, default=40)
    ap.add_argument("--max-frac", type=float, default=0.75)
    ap.add_argument("--commission", type=float, default=0.0)
    ap.add_argument("--tax", type=float, default=0.0)
    ap.add_argument("--seed", type=float, default=None)
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--data", type=Path,
                    default=Path(__file__).resolve().parent / "data" / "leveraged-etf")
    a = ap.parse_args()

    if a.selftest or not a.rules:
        return selftest()

    import pandas as pd

    over: dict = {"commission": a.commission, "tax": a.tax}
    if a.seed is not None:
        over["seed"] = a.seed
    r = Rules.load(a.rules, a.ticker, a.splits, **over)

    df = pd.read_parquet(a.data / f"{a.ticker}.parquet")
    candles = [{"date": d.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
               for d, o, h, lo, c in
               df[["date", "open", "high", "low", "close"]].itertuples(index=False)]
    if a.start:
        candles = [c for c in candles if c["date"] >= a.start]
    if a.end:
        candles = [c for c in candles if c["date"] <= a.end]

    res = backtest(candles, r, plan_fn=make_plan_fn(a.max_frac))
    st = res.state
    assert st is not None
    print(f"{a.ticker} {a.splits}분할 base={r.base_pct:g} maxFrac={a.max_frac:g}  "
          f"{candles[0]['date']}~{candles[-1]['date']} ({len(candles)}일)")
    print(f"  사이클 {len(res.cycles)}  역전 {res.reverse_days}일  체결 {st.fills}  "
          f"회전 {st.buy_notional / r.seed:.0f}x")
    print(f"  평가금 ${res.final_equity:,.0f}  CAGR {res.cagr:.2f}%  MDD {res.mdd:.1f}%  "
          f"수수료 ${st.commission_paid:,.0f}  세금 ${st.tax_paid:,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
