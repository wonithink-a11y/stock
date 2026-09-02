#!/usr/bin/env python
"""sector_neutral_pbr_growth 를 **월별 시가평가(MTM)** 로 재측정 — Tier 2 정본.

왜 다시 재나
------------
run_sector_neutral_pbr_growth.py 는 run_pbr_value_v1.py 를 따라 **실현손익
누적** 곡선으로 지표를 냈는데, 그 방식은 이 프로젝트가 2026-08-22 에 이미
폐기한 것이다: 연속보유 장기포지션의 손익을 마지막 청산일에 몰아주기 때문에
미실현 낙폭이 곡선에 아예 안 나타나 MDD 가 얕아지고 Sharpe 가 부풀려진다.
그때 PBR 의 "Sharpe 2.25 · MDD -10.5%" 가 실은 착시였고 정확한 값은
"Sharpe 0.46 · MDD -21.7%" 였다.

이번 실행에서도 같은 증상이 그대로 나왔다(MDD -9.0%, Sharpe 2.17) - 롱온리
한국주식이 2020 코로나·2022 를 지나며 나올 수 없는 값이다. 그래서
pbr_vs_ew_monthly_mtm.py 의 `schedule_with_monthly_mtm` 을 **그대로 import 해서**
다시 잰다(로직 복제 없음).

  python run_sector_neutral_mtm.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import (  # noqa: E402  — 검증된 MTM 로직을 재사용한다
    schedule_with_monthly_mtm, curve_metrics, annual_returns_mtm, START, END, REPO_ROOT)

STRATEGIES = ["sector_neutral_pbr_growth_v1",
              "sector_neutral_pbr_growth_v1_top30",
              "ew_benchmark_liquid_v1"]
PERIODS = [("TRAIN", "2016-01-01", "2022-06-30"),
           ("VALID", "2022-07-01", "2024-01-01"),
           ("TEST", "2024-01-02", "2026-08-14")]


def measure(strategy_id):
    t0 = time.time()
    base = run_smoke(strategy_id, START, END, REPO_ROOT)
    params = base["params"]
    cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"],
        fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snaps = schedule_with_monthly_mtm(
        base["resolved"], cfg, base["bars_by_ticker"], base["calendar"], START, END)
    print(f"  {strategy_id}: 청산 {len(portfolio.closed_positions):,} · "
          f"종료시 미청산 {len(portfolio.open_positions)} · 스냅샷 {len(snaps)}개월 "
          f"({time.time() - t0:.0f}s)", flush=True)
    return snaps, portfolio


def sub_metrics(snaps, lo, hi):
    """구간 내 스냅샷만 잘라 그 구간의 CAGR/MDD/Sharpe 를 낸다."""
    seg = [(d, v) for d, v in snaps if lo <= d <= hi]
    if len(seg) < 3:
        return None
    m = curve_metrics(seg)
    rets = np.array([seg[i][1] / seg[i - 1][1] - 1 for i in range(1, len(seg))], dtype=float)
    m["nMonths"] = len(seg)
    m["meanMonthly"] = float(rets.mean())
    return m


def main():
    out = {}
    for sid in STRATEGIES:
        snaps, _ = measure(sid)
        out[sid] = {"overall": curve_metrics(snaps),
                    "annual": annual_returns_mtm(snaps),
                    "byPeriod": {n: sub_metrics(snaps, lo, hi) for n, lo, hi in PERIODS},
                    "monthlySnapshots": len(snaps)}

    bench = out["ew_benchmark_liquid_v1"]
    print(f"\n{'전략':<36}{'CAGR':>9}{'MDD':>9}{'Sharpe':>8}{'Calmar':>8}{'총수익':>10}")
    print("-" * 80)
    for sid in STRATEGIES:
        r = out[sid]["overall"]
        # curve_metrics 는 calmar 를 안 낸다 - 여기서 계산한다(없는 값을 0 으로 찍지 않는다)
        cal = r["cagr"] / abs(r["mdd"]) if r.get("mdd") else None
        r["calmar"] = cal
        print(f"{sid:<36}{r['cagr'] * 100:>8.2f}%{r['mdd'] * 100:>8.1f}%"
              f"{(r.get('sharpe') or 0):>8.2f}{cal if cal is None else f'{cal:>8.2f}'}"
              f"{r['totalReturn'] * 100:>9.1f}%")

    print(f"\n구간별 (벤치마크 대비 CAGR 격차)")
    print(f"{'전략':<36}{'구간':<7}{'개월':>5}{'CAGR':>9}{'벤치':>9}{'격차':>9}{'MDD':>9}")
    print("-" * 88)
    for sid in STRATEGIES[:-1]:
        for n, _, _ in PERIODS:
            p, b = out[sid]["byPeriod"].get(n), bench["byPeriod"].get(n)
            if not p or not b:
                continue
            gap = p["cagr"] - b["cagr"]
            mark = "" if gap > 0 else "  <<"
            print(f"{sid if n == 'TRAIN' else '':<36}{n:<7}{p['nMonths']:>5}"
                  f"{p['cagr'] * 100:>8.2f}%{b['cagr'] * 100:>8.2f}%{gap * 100:>8.2f}%p"
                  f"{p['mdd'] * 100:>8.1f}%{mark}")
        print()

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                           f"{time.strftime('%Y-%m-%d')}-sector-neutral-smoke")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "mtm.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"method": "monthly mark-to-market equity curve "
                             "(pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm 재사용)",
                   "period": f"{START} ~ {END}",
                   "note": "실현손익 누적 방식은 2026-08-22 에 폐기됨 - 미실현 낙폭이 "
                           "곡선에 안 나타나 MDD 가 얕아지고 Sharpe 가 부풀려진다.",
                   "results": out}, f, ensure_ascii=False, indent=2, default=str)
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
