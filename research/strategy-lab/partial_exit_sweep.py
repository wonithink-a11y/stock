#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""부분 익절(분할매도) 검증 — "얼마 오르면 얼마나 팔아야 잘 판 건가".

사용자가 2026-08-25 에 동의했으나 착수되지 않은 채 남아 있던 항목이다
(세션인수인계-2026-08-25.md 1.3). 이 저장소의 기존 실측은 전부 **전량 매도**
전제 위에서 돌았고, "+X% 에서 절반 팔기"는 격자 안에 아예 없었다.

  같은 진입 · 같은 리밸런싱 · 같은 비용 · 같은 최종 청산.
  **바뀌는 것은 '보유 중에 일부를 미리 파는가' 하나뿐이다.**

엔진 무변경 원칙: engine/execution/executor.py 와 engine/runner.py 는 안 건드린다.
Portfolio.process_day 에 부분청산을 넣고(shares 인자를 이미 받고 있었다),
연구용 스케줄러(schedule_with_monthly_mtm)에 opt-in partial_exits 를 얹었다.
둘 다 인자를 안 주면 기존 동작과 바이트 단위로 같다.

  python partial_exit_sweep.py --selftest
  python partial_exit_sweep.py --strategy pbr_value_v1 --triggers 10,20,30 --fractions 0.3,0.5
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.execution.contracts import Fill                       # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig            # noqa: E402
from engine.runner import load_strategy, run_smoke                # noqa: E402
from pbr_vs_ew_monthly_mtm import (                               # noqa: E402
    curve_metrics, schedule_with_monthly_mtm)
from report_tier2_oos import SEGMENTS, segment_metrics            # noqa: E402

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
OUT_DIR = os.path.join(LAB, "reports", "2026-09-04-partial-exit")


def _sell_slippage(price, slippage_bps):
    return price * (1 - slippage_bps / 10000) if slippage_bps else price


def scale_out_events(resolved, bars_by_ticker, trigger_pct, fraction, exit_cost_bps, slippage_bps):
    """거래마다 진입가 x (1+trigger) 에 처음 닿은 날을 찾는다.

    - 진입일 **다음** 세션부터 원래 청산일 **전** 세션까지만 본다. 청산일 당일에
      닿는 것은 어차피 그날 전량 청산되므로 부분청산이 아니다.
    - 체결가 규약은 executor.py 의 TARGET 과 같다(트리거 가격에 슬리피지) -
      갭 상승분을 이득으로 세지 않는 보수적 쪽이다.
    - 한 거래당 최대 1회. 여러 번 나눠 파는 격자는 이번 범위 밖이다.
    """
    out = {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        bars = bars_by_ticker.get(order.symbol)
        if bars is None:
            continue
        trig = entry_fill.fill_price * (1 + trigger_pct)
        for d in [str(x) for x in bars.index.astype(str)]:
            if d <= entry_fill.fill_date or d >= exit_fill.fill_date:
                continue
            if float(bars.loc[d, "high"]) >= trig:
                price = _sell_slippage(trig, slippage_bps)
                out[(order.symbol, order.order_date)] = (
                    d, Fill(order, d, price, "TARGET", exit_cost_bps, slippage_bps), fraction)
                break
    return out


def random_timing_control(events, resolved, bars_by_ticker, seed):
    """대조군: 같은 거래·같은 비율·같은 건수를 팔되 **파는 날만 무작위**로 바꾼다.

    이걸로 "익절 트리거라는 시점 선택"과 "그냥 일부를 미리 판 것"을 가른다 -
    simulate_exits.py 의 --random-entries 와 같은 원리다. 대조군이 실측만큼
    좋으면 개선은 타이밍이 아니라 노출 축소에서 온 것이다."""
    import random
    rnd = random.Random(seed)
    by_key = {(o.symbol, o.order_date): (ef, xf) for (_, o, ef, xf, _, _) in resolved}
    out = {}
    for key, (_, fill, frac) in events.items():
        ef, xf = by_key[key]
        bars = bars_by_ticker.get(key[0])
        days = [str(d) for d in bars.index.astype(str)
                if ef.fill_date < str(d) < xf.fill_date]
        if not days:
            continue
        d = rnd.choice(days)
        price = float(bars.loc[d, "close"])
        out[key] = (d, Fill(fill.order, d, price, "TARGET", fill.cost_bps, fill.slippage_bps), frac)
    return out


def load_run(strategy_id, start, end):
    """run_smoke 는 격자 전체에서 같은 결과다(진입·신호·비용 무변경) - 한 번만
    돌리고 재사용한다. 이걸 매 격자점마다 다시 돌리면 대부분의 시간이 거기 간다."""
    mod = load_strategy(strategy_id, REPO_ROOT)
    return run_smoke(strategy_id, start, end, REPO_ROOT, rule_module=mod)


def measure(strategy_id, trigger_pct, fraction, start, end, run, random_seed=None):
    t0 = time.time()
    p = run["params"]
    cfg = PortfolioConfig(
        initial_capital=p["portfolio"]["initialCapital"],
        max_positions=p["portfolio"]["maxPositions"],
        equal_weight=p["portfolio"]["equalWeight"],
        fractional_shares=p["portfolio"]["fractionalShares"],
        tie_break=p["portfolio"]["tieBreak"])
    pe = None
    if trigger_pct is not None:
        pe = scale_out_events(run["resolved"], run["bars_by_ticker"], trigger_pct, fraction,
                              p["cost"]["exitCostBps"], p["cost"]["slippageBps"])
        if random_seed is not None:
            pe = random_timing_control(pe, run["resolved"], run["bars_by_ticker"], random_seed)
    portfolio, snaps = schedule_with_monthly_mtm(
        run["resolved"], cfg, run["bars_by_ticker"], run["calendar"], start, end,
        partial_exits=pe)
    partials = sum(1 for c in portfolio.closed_positions if c.get("partial"))
    label = ("전량 보유(현재)" if trigger_pct is None
             else "+{:.0f}% 에서 {:.0f}% 매도".format(trigger_pct * 100, fraction * 100))
    if random_seed is not None:
        label = "[대조군 seed{}] {:.0f}% 무작위시점 매도".format(random_seed, fraction * 100)
    return {"strategyId": strategy_id, "label": label,
            "triggerPct": trigger_pct, "fraction": fraction,
            "period": start + " ~ " + end, "accountingMethod": "monthly mark-to-market",
            "resultTable": curve_metrics(snaps),
            "snapshots": [[d, float(e)] for d, e in snaps],
            "segments": segment_metrics([[d, float(e)] for d, e in snaps]),
            "closedPositionCount": len(portfolio.closed_positions),
            "partialExitCount": partials,
            "scaleOutCandidates": len(pe or {}),
            "elapsedSeconds": round(time.time() - t0, 1)}


def print_table(rows):
    print("\n{:26} {:>8} {:>9} {:>8} {:>7} {:>7} | {:>7}{:>8}{:>8}".format(
        "규칙", "CAGR", "MDD", "Sharpe", "Calmar", "부분", "TRAIN", "VALID", "TEST"))
    for r in rows:
        m = r["resultTable"]
        cal = m["cagr"] / abs(m["mdd"]) if m["mdd"] else 0
        seg = "".join("{:8.3f}".format(r["segments"][s]["sharpe"])
                      if r["segments"][s] and r["segments"][s]["sharpe"] is not None else "       -"
                      for s in SEGMENTS)
        print("{:26} {:>7.2%} {:>8.2%} {:>8.4f} {:>7.3f} {:>7} | {}".format(
            r["label"][:26], m["cagr"], m["mdd"], m["sharpe"] or 0, cal,
            r["partialExitCount"], seg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="pbr_value_v1")
    ap.add_argument("--triggers", default="10,20,30", help="익절 트리거 %, 쉼표 구분")
    ap.add_argument("--fractions", default="0.5", help="매도 비율, 쉼표 구분")
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="2026-08-14")
    ap.add_argument("--random-seeds", default="", help="무작위 시점 대조군 seed, 쉼표 구분")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    os.makedirs(OUT_DIR, exist_ok=True)
    seeds = [int(x) for x in a.random_seeds.split(",")] if a.random_seeds else []
    out = os.path.join(OUT_DIR, a.strategy + ("_control" if seeds else "") + ".json")
    base = [(float(t) / 100, float(f), None)
            for t in a.triggers.split(",") for f in a.fractions.split(",")]
    grid = ([(t, f, sd) for (t, f, _) in base for sd in seeds] if seeds
            else [(None, None, None)] + base)
    print("[{}] {} run_smoke 1회 로드 ...".format(time.strftime("%H:%M:%S"), a.strategy), flush=True)
    run = load_run(a.strategy, a.start, a.end)
    rows = []
    for trig, frac, sd in grid:
        print("[{}] {} trigger={} fraction={} seed={} ...".format(
            time.strftime("%H:%M:%S"), a.strategy, trig, frac, sd), flush=True)
        rows.append(measure(a.strategy, trig, frac, a.start, a.end, run, sd))
        m = rows[-1]["resultTable"]
        print("    {:.2%} / {:.2%} / {:.4f}  부분청산 {}건  ({}s)".format(
            m["cagr"], m["mdd"], m["sharpe"] or 0, rows[-1]["partialExitCount"],
            rows[-1]["elapsedSeconds"]), flush=True)
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows},
                      f, ensure_ascii=False, indent=1, default=str)
    print_table(rows)
    print("\n저장: " + out)


def selftest():
    import pandas as pd

    class FakeOrder:
        symbol = "TEST1"
        order_date = "2026-01-02"

    bars = pd.DataFrame(
        {"high": [100, 105, 120, 130], "low": [95] * 4, "close": [100, 105, 120, 130]},
        index=["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"])
    o = FakeOrder()
    ef = Fill(o, "2026-01-02", 100.0, "OPEN", 15, 0)
    xf = Fill(o, "2026-01-07", 130.0, "TIME_EXIT", 15, 0)
    resolved = [(None, o, ef, xf, None, None)]

    ev = scale_out_events(resolved, {"TEST1": bars}, 0.10, 0.5, 15, 0)
    assert list(ev) == [("TEST1", "2026-01-02")], ev
    d, fill, frac = ev[("TEST1", "2026-01-02")]
    assert d == "2026-01-06", d                   # high 120 >= 110 인 첫 날(01-05 는 105)
    assert abs(fill.fill_price - 110.0) < 1e-9, fill.fill_price   # 갭 이득을 세지 않는다
    assert frac == 0.5 and fill.fill_type == "TARGET"

    # 청산일 당일에 닿는 것은 부분청산이 아니다(130 은 01-07 = 청산일)
    assert scale_out_events(resolved, {"TEST1": bars}, 0.30, 0.5, 15, 0) == {}
    # 아예 안 닿으면 없음
    assert scale_out_events(resolved, {"TEST1": bars}, 1.00, 0.5, 15, 0) == {}
    # 진입일 당일 고가는 세지 않는다(진입 다음 세션부터 본다)
    b2 = bars.copy()
    b2.loc["2026-01-02", "high"] = 999
    got = scale_out_events(resolved, {"TEST1": b2}, 0.10, 0.5, 15, 0)
    assert got[("TEST1", "2026-01-02")][0] == "2026-01-06", got
    # 슬리피지가 있으면 체결가가 트리거보다 불리하다
    _, f2, _ = scale_out_events(resolved, {"TEST1": bars}, 0.10, 0.5, 15, 50)[("TEST1", "2026-01-02")]
    assert f2.fill_price < 110.0, f2.fill_price
    print("selftest ok (6건)")


if __name__ == "__main__":
    main()
