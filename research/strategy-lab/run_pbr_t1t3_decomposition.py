#!/usr/bin/env python
"""PBR baseline vs dropout vs maxexcl - 개선이 T1(저유동성)에서만 나타나고
T3(고유동성/대형주)에서 반전되는지 확인. 이 프로젝트가 3~4번 재현한 패턴
(PBR·LOWMOM60+수급 등 "저유동성에서만 플러스, 대형주에서 반전")과 두 신규
실험(2026-08-26 findings)이 겹치는지가 이 스크립트의 유일한 질문이다.

절대임계값(turnover20>=1억원, absolute_liquidity_decile_check.py와 동일 기준
- 상대 tercile은 그 자체가 방향성 있는 신호였다는 게 이미 확인됐다, 규칙3
CLAUDE.md 참고)으로 진입 시점 거래를 T1/T3로 나눠, baseline과 각 변형의
거래당 평균수익률·승률을 버킷별로 비교한다. 포트폴리오 MTM 곡선은 슬롯을
공유해 버킷별로 못 쪼개므로, 이 프로젝트의 decile 분석과 같은 방식대로
거래 단위 평균으로 비교한다.

  python run_pbr_t1t3_decomposition.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
START, END = "2016-01-01", "2026-08-14"
MIN_TURNOVER = 100_000_000.0
STRATEGIES = ["pbr_value_v1", "pbr_value_v1_dropout", "pbr_value_v1_maxexcl"]


def build_turnover_lookup(bars_by_ticker):
    lookup = {}
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        turnover20 = (bars["close"] * bars["volume"]).rolling(20).mean()
        idx = bars.index.astype(str)
        lookup[ticker] = dict(zip(idx, turnover20.values))
    return lookup


def trade_return(pos):
    entry = pos["entry"]
    cost_basis = entry.fill_price * pos["shares"] * (1 + entry.cost_bps / 10000)
    return pos["pnl"] / cost_basis if cost_basis else None


def bucket_stats(rets):
    rets = [r for r in rets if r is not None]
    if not rets:
        return {"count": 0, "meanReturn": None, "winRate": None}
    arr = np.array(rets)
    return {"count": len(arr), "meanReturn": round(float(arr.mean()), 4),
            "winRate": round(float((arr > 0).mean()), 4)}


def run_and_split(strategy_id):
    t0 = time.time()
    base = run_smoke(strategy_id, START, END, REPO_ROOT)
    resolved, params = base["resolved"], base["params"]
    bars_by_ticker, calendar = base["bars_by_ticker"], base["calendar"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, _ = schedule_with_monthly_mtm(resolved, portfolio_cfg, bars_by_ticker, calendar, START, END)
    turnover_lookup = build_turnover_lookup(bars_by_ticker)

    trades = []
    for pos in portfolio.closed_positions:
        tv = turnover_lookup.get(pos["symbol"], {}).get(pos["entry_date"])
        r = trade_return(pos)
        if tv is None or (isinstance(tv, float) and np.isnan(tv)):
            continue
        trades.append((tv, r))

    # 절대임계값(전체 유니버스 기준 "고유동성") 분해 - PBR 자체가 이미 유동성
    # 필터를 거친 선별 유니버스라 거의 전부 T3로 잡힐 수 있다(참고용)
    t1_abs = [r for tv, r in trades if tv < MIN_TURNOVER]
    t3_abs = [r for tv, r in trades if tv >= MIN_TURNOVER]

    # 전략 자체 보유종목 내 상대 tercile - "PBR이 고른 종목들 중 상대적으로
    # 작은/큰 쪽" 분해. 전체 유니버스에 상대 tercile을 필터로 적용하는 것과
    # 달리(그 자체가 방향성 신호였던 문제, CLAUDE.md 참고) 이건 이미 고정된
    # 거래 집합을 사후 진단용으로만 나누는 것이라 같은 함정이 아니다.
    tvs = sorted(tv for tv, _ in trades)
    n = len(tvs)
    lo_cut, hi_cut = tvs[n // 3], tvs[(2 * n) // 3]
    t1_rel = [r for tv, r in trades if tv <= lo_cut]
    t3_rel = [r for tv, r in trades if tv >= hi_cut]

    print(f"  {strategy_id}: {len(portfolio.closed_positions)} closed, {len(trades)} liquidity-known "
          f"(abs T1={len(t1_abs)} T3={len(t3_abs)}, rel-tercile T1={len(t1_rel)} T3={len(t3_rel)}) "
          f"({time.time()-t0:.0f}s)")
    return {
        "totalClosed": len(portfolio.closed_positions), "liquidityKnown": len(trades),
        "abs_t1_under1e8": bucket_stats(t1_abs), "abs_t3_over1e8": bucket_stats(t3_abs),
        "relTercile_t1_bottom33pct": bucket_stats(t1_rel), "relTercile_t3_top33pct": bucket_stats(t3_rel),
    }


def main():
    print(f"=== PBR T1/T3 decomposition (baseline vs dropout vs maxexcl), {START} ~ {END} ===")
    results = {sid: run_and_split(sid) for sid in STRATEGIES}
    print("\n", json.dumps(results, ensure_ascii=False, indent=2, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pbr-t1t3-decomposition")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-t1t3-decomposition.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "2026-08-26 dropout·MAX제외 두 실험이 이 프로젝트가 반복 관측한 "
                       "'저유동성에서만 플러스, 대형주(T3)에서 반전' 패턴과 겹치는지 확인. "
                       "abs_*: 절대임계값(turnover20>=1억원, 전체 유니버스 기준) 분해 - PBR "
                       "자체가 이미 유동성 필터를 거친 선별 유니버스라 참고용. relTercile_*: "
                       "전략이 실제로 고른 종목들 내 상대적 하위/상위 33% 분해(이미 고정된 "
                       "거래 집합의 사후 진단이라 상대 tercile을 필터로 쓸 때의 오염 문제와 "
                       "다르다) - 거래단위 평균수익률·승률 비교, 포트폴리오 MTM 곡선이 아님 "
                       "(슬롯 공유로 버킷별 분리 불가).",
            "minTurnover": MIN_TURNOVER, "period": f"{START} ~ {END}",
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
