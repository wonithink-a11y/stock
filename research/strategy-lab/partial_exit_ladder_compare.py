#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""일본 투자자(인스타 게시물, 2026-09-28) 상승 사다리 매도 — **기록 전용 탐색 비교**.

부분 익절 그림자(사전등록 +20%/70% 하나만 판정)와 같은 표본·같은 엔진에서 나란히 잰다. 이 결과로 규칙을 고르지 않는다
(이미 여러 번 본 in-sample — 다중검정). 하락 시 추가 매수(물타기) 절반은 이 엔진이 지원하지 않아 재지 않는다.

사다리(게시물): +25% 10% · +35% 20% · +45% 30% · +60% 40% · +100% 전량. 비율 해석이 둘이라 둘 다 잰다.
  L-A 누적 목표: 매도 누계가 10→20→30→40%, +100% 에서 전량
  L-B 원래 수량 기준: 10+20+30+40 = +60% 에서 전량 소진
한 날 여러 단계를 넘으면 한 번에 합쳐 팔고, 체결가는 넘은 단계 중 **가장 낮은 트리거**(보수적).

  python research/strategy-lab/partial_exit_ladder_compare.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.execution.contracts import Fill                        # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig             # noqa: E402
from partial_exit_sweep import _sell_slippage, load_run, measure    # noqa: E402
from pbr_vs_ew_monthly_mtm import curve_metrics, schedule_with_monthly_mtm  # noqa: E402
from report_tier2_oos import segment_metrics                       # noqa: E402

STRATEGY, START, END = "pbr_value_v1", "2016-01-01", "2026-08-14"   # partial-exit-scale-out-2026-09 와 같은 표본
LADDERS = {
    "L-A 누적 10/20/30/40%, +100% 전량": [(0.25, 0.10), (0.35, 0.20), (0.45, 0.30), (0.60, 0.40), (1.00, 1.00)],
    "L-B 원래 수량 10+20+30+40%(+60% 소진)": [(0.25, 0.10), (0.35, 0.30), (0.45, 0.60), (0.60, 1.00)],
}
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "2026-09-04-partial-exit", "ladder_fujimoto.json")


def ladder_events(resolved, bars_by_ticker, levels, exit_cost_bps, slippage_bps):
    """levels = [(트리거, 누적 매도 목표)]. 반환 {key: [(date, fill, 잔여 대비 비율), ...]} — 하루 최대 1건."""
    out = {}
    for _, order, ef, xf, _, _ in resolved:
        bars = bars_by_ticker.get(order.symbol)
        if bars is None:
            continue
        done, chain = 0.0, []
        nxt = 0
        for d in [str(x) for x in bars.index.astype(str)]:
            if d <= ef.fill_date or d >= xf.fill_date or nxt >= len(levels) or done >= 1.0:
                continue
            hi = float(bars.loc[d, "high"])
            first, target = None, done
            while nxt < len(levels) and hi >= ef.fill_price * (1 + levels[nxt][0]):
                first = first if first is not None else levels[nxt][0]
                target = levels[nxt][1]
                nxt += 1
            if first is None:
                continue
            frac = 1.0 if target >= 1.0 else (target - done) / (1 - done)
            price = _sell_slippage(ef.fill_price * (1 + first), slippage_bps)
            chain.append((d, Fill(order, d, price, "TARGET", exit_cost_bps, slippage_bps), frac))
            done = target
        if chain:
            out[(order.symbol, order.order_date)] = chain
    return out


def main():
    run = load_run(STRATEGY, START, END)
    p = run["params"]
    rows = [measure(STRATEGY, None, None, START, END, run), measure(STRATEGY, 0.20, 0.70, START, END, run)]
    cfg = PortfolioConfig(initial_capital=p["portfolio"]["initialCapital"], max_positions=p["portfolio"]["maxPositions"],
                          equal_weight=p["portfolio"]["equalWeight"], fractional_shares=p["portfolio"]["fractionalShares"],
                          tie_break=p["portfolio"]["tieBreak"])
    for label, levels in LADDERS.items():
        pe = ladder_events(run["resolved"], run["bars_by_ticker"], levels, p["cost"]["exitCostBps"], p["cost"]["slippageBps"])
        portfolio, snaps = schedule_with_monthly_mtm(run["resolved"], cfg, run["bars_by_ticker"], run["calendar"],
                                                     START, END, partial_exits=pe)
        rows.append({"label": label, "resultTable": curve_metrics(snaps),
                     "segments": segment_metrics([[d, float(e)] for d, e in snaps]),
                     "partialExitCount": sum(1 for c in portfolio.closed_positions if c.get("partial")),
                     "tradesTouched": len(pe), "events": sum(len(v) for v in pe.values())})
    trades = len(run["resolved"])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"strategy": STRATEGY, "period": [START, END], "trades": trades,
                   "rows": [{k: v for k, v in r.items() if k != "snapshots"} for r in rows]}, f, ensure_ascii=False, indent=1, default=str)
    print(f"거래 {trades}건")
    print(f"{'규칙':36} {'CAGR':>7} {'MDD':>8} {'Sharpe':>7} {'부분':>5} {'TRAIN':>7} {'VALID':>7} {'TEST':>7}")
    for r in rows:
        m, s = r["resultTable"], r["segments"]
        seg = "".join(f"{(s[k] or {}).get('sharpe') or 0:7.3f} " for k in s)
        print(f"{r['label'][:36]:36} {m['cagr']:7.2%} {m['mdd']:8.2%} {m['sharpe'] or 0:7.3f} {r['partialExitCount']:5} {seg}")
    print("저장:", OUT)


if __name__ == "__main__":
    main()
