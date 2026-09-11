#!/usr/bin/env python
"""LW3 ablation - '래리 윌리엄스 3박자'의 세 조건이 각각 무엇을 더하는가.

같은 엔진·같은 유니버스·같은 비용·같은 기간에서 필터만 켜고 끈다.
성과 곡선은 **월말 시가평가(MTM)**로 만든다 - 실현손익 누적 방식은 장기
보유분의 손익을 청산 연도에 몰아 넣어 MDD·Sharpe를 왜곡한다(2026-08-22
발견, 2026-09-02 재발). pbr_vs_ew_monthly_mtm.py 의 파이프라인을 수정 없이
재사용한다.

라이브 policy.json 을 건드리지 않는다 - PARAMS 를 인메모리로 복제해 바꾼다
(2026-09-10 capacity test 에서 파일 바꿔치기를 제거한 것과 같은 이유:
페이퍼 엔진이 10분마다 같은 파일을 읽는다).

  python run_lw3_ablation.py                    # 전부
  python run_lw3_ablation.py --variants A_donchian
  python run_lw3_ablation.py --end 2018-12-31   # 빠른 확인용
"""
import argparse
import copy
import json
import os
import sys
import time
from datetime import date as _date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.metrics.metrics import trade_stats  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.runner import load_strategy, run_smoke  # noqa: E402
from pbr_vs_ew_monthly_mtm import (annual_returns_mtm, curve_metrics,  # noqa: E402
                                   schedule_with_monthly_mtm)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRATEGY_ID = "lw3_donchian_v1"
START, END = "2016-01-01", "2026-08-14"

# 익절선을 사실상 없애는 값. 엔진은 target = entry + rewardRisk * stop_distance
# 를 늘 계산하므로 '끈다'는 스위치가 따로 없다 - 도달 불가능하게 만들어
# 손절 아니면 시간청산으로만 끝나게 한다.
NO_TARGET = 1e9

VARIANTS = {
    "A_donchian":         {"filters.volume": False, "filters.lwti": False},
    "B_donchian_volume":  {"filters.volume": True,  "filters.lwti": False},
    # C 는 LWTI 단독 기여를 분리한다. D-B 는 "거래량이 이미 있는 상태에서의
    # LWTI 한계 기여"라 두 필터의 상호작용과 섞인다 - C-A 가 순수 LWTI 다.
    "C_donchian_lwti":    {"filters.volume": False, "filters.lwti": True},
    "D_three_slope":      {"filters.volume": True,  "filters.lwti": True},
    "D_three_midline":    {"filters.volume": True,  "filters.lwti": True,
                           "indicators.lwti.colorRule": "midline"},
    "D_three_transition": {"filters.volume": True,  "filters.lwti": True,
                           "signal.lwtiMode": "transition"},
    "E_no_target":        {"filters.volume": True,  "filters.lwti": True,
                           "risk.rewardRisk": NO_TARGET},
}

LABELS = {
    "A_donchian":         "A  돈치안20 돌파만",
    "B_donchian_volume":  "B  + 거래량MA20",
    "C_donchian_lwti":    "C  + LWTI(slope) (거래량 없음)",
    "D_three_slope":      "D  + LWTI(slope)  = 3박자",
    "D_three_midline":    "D' LWTI 색상규칙을 midline 으로",
    "D_three_transition": "D\" LWTI 를 당일 전환으로 (엄격)",
    "E_no_target":        "E  D에서 2:1 익절 제거 (손절·시간청산만)",
}


def build_rule(overrides):
    rule = load_strategy(STRATEGY_ID, REPO_ROOT)
    rule.PARAMS = copy.deepcopy(rule.PARAMS)
    for path, value in overrides.items():
        node, keys = rule.PARAMS, path.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return rule


def _ordinal(d):
    y, m, dd = map(int, d.split("-"))
    return _date(y, m, dd).toordinal()


def trades_from(portfolio):
    out = []
    for p in portfolio.closed_positions:
        entry, exit_ = p["entry"], p["exit"]
        cost_basis = entry.fill_price * p["shares"]
        out.append({
            "pnl": p["pnl"],
            "ret": (p["pnl"] / cost_basis) if cost_basis else 0.0,
            "holding_sessions": _ordinal(exit_.fill_date) - _ordinal(p["entry_date"]),
            "exit_type": exit_.fill_type,
        })
    return out


def resolved_trade_stats(resolved):
    """포트폴리오 슬롯 제약을 **빼고** 모든 신호의 결과를 잰다.

    ★ 이게 ablation 의 본 지표다. maxPositions=10 인데 신호는 수만 건이라
    포트폴리오 경로는 대부분의 신호를 버리고 tie_break(ticker_ascending)가
    누가 들어갈지를 정한다 - 그 숫자를 필터끼리 비교하면 '필터가 좋은가'가
    아니라 '알파벳 앞쪽 종목이 어느 쪽 풀에 남았는가'를 재게 된다.
    여기서는 체결 가능한 모든 신호를 1건씩 동일하게 세어 필터의 예측력만 본다.
    """
    rets, holds, exits = [], [], {}
    for _sig, order, entry_fill, exit_fill, _spec, _atr in resolved:
        entry = entry_fill.fill_price * (1 + entry_fill.cost_bps / 1e4)
        exit_ = exit_fill.fill_price * (1 - exit_fill.cost_bps / 1e4)
        rets.append(exit_ / entry - 1)
        holds.append(_ordinal(exit_fill.fill_date) - _ordinal(entry_fill.fill_date))
        exits[exit_fill.fill_type] = exits.get(exit_fill.fill_type, 0) + 1
    if not rets:
        return {"tradeCount": 0}
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_win, gross_loss = sum(wins), -sum(losses)
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1) if n > 1 else 0.0
    sd = var ** 0.5
    return {
        "tradeCount": n,
        "avgReturnNet": round(mean, 5),
        "medianReturnNet": round(sorted(rets)[n // 2], 5),
        "winRate": round(len(wins) / n, 4),
        "profitFactor": round(gross_win / gross_loss, 4) if gross_loss > 0 else None,
        "avgWin": round(sum(wins) / len(wins), 5) if wins else None,
        "avgLoss": round(sum(losses) / len(losses), 5) if losses else None,
        "avgHoldingSessions": round(sum(holds) / n, 1),
        "tStat": round(mean / (sd / n ** 0.5), 3) if sd > 0 else None,
        "exitTypeCounts": exits,
    }


def run_variant(name, start, end):
    t0 = time.time()
    rule = build_rule(VARIANTS[name])
    base = run_smoke(STRATEGY_ID, start, end, REPO_ROOT, rule_module=rule)
    params, diag = base["params"], base["diag"]

    cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"],
        fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snaps = schedule_with_monthly_mtm(
        base["resolved"], cfg, base["bars_by_ticker"], base["calendar"], start, end)

    trades = trades_from(portfolio)
    stats = trade_stats(trades) if trades else {"tradeCount": 0}
    metrics = curve_metrics(snaps) if len(snaps) > 1 else {}
    rets = [t["ret"] for t in trades]

    exits = {}
    for t in trades:
        exits[t["exit_type"]] = exits.get(t["exit_type"], 0) + 1

    return {
        "variant": name,
        "label": LABELS[name],
        "overrides": {k: v for k, v in VARIANTS[name].items()},
        "signalCount": diag["signalCount"],
        "portfolioEligibleTradeCount": diag["portfolioEligibleTradeCount"],
        "tickersScanned": diag["tickersScanned"],
        "runClass": diag["runClass"],
        "resolvedTradeStats": resolved_trade_stats(base["resolved"]),
        "metricsMTM": metrics,
        "annualReturnsMTM": annual_returns_mtm(snaps) if len(snaps) > 1 else {},
        "tradeStats": {k: (round(v, 4) if isinstance(v, float) else v)
                       for k, v in stats.items()},
        "avgTradeReturn": round(sum(rets) / len(rets), 4) if rets else None,
        "exitTypeCounts": exits,
        "closedPositionCount": len(portfolio.closed_positions),
        "openPositionCountAtEnd": len(portfolio.open_positions),
        "monthlySnapshots": len(snaps),
        "elapsedSec": round(time.time() - t0, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="*", default=list(VARIANTS))
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--out", default=os.path.join(
        "findings", "lw3-donchian-ablation", "lw3_ablation_results.json"))
    args = ap.parse_args()

    print("=== LW3 ablation  %s ~ %s ===" % (args.start, args.end))
    results = []
    for name in args.variants:
        if name not in VARIANTS:
            raise SystemExit("모르는 변형: %s" % name)
        r = run_variant(name, args.start, args.end)
        results.append(r)
        m, rs = r["metricsMTM"], r["resolvedTradeStats"]
        print("  %-38s 신호%6d · 전건 %5s건 평균%8s 승률%6s t=%6s │ 포트 CAGR%8s MDD%8s Sh%7s  (%ss)"
              % (r["label"], r["signalCount"], rs.get("tradeCount"),
                 rs.get("avgReturnNet"), rs.get("winRate"), rs.get("tStat"),
                 m.get("cagr"), m.get("mdd"), m.get("sharpe"), r["elapsedSec"]))

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    # ★ 부분 실행이 기존 결과를 지우지 않는다. --variants 로 한 변형만 돌리면
    # 예전에는 나머지 다섯이 파일에서 사라졌다(2026-09-11 수정). 같은 창이 아닌
    # 결과는 섞지 않는다 - 창이 바뀌면 이전 결과를 버린다(비교가 안 되는 값이다).
    prior = []
    if os.path.exists(args.out):
        try:
            old = json.load(open(args.out, encoding="utf-8"))
            if old.get("window") == {"start": args.start, "end": args.end}:
                done = {r["variant"] for r in results}
                prior = [r for r in old.get("results", []) if r["variant"] not in done]
            else:
                print("  (창이 달라 이전 결과 %d건을 버린다: %s)"
                      % (len(old.get("results", [])), old.get("window")))
        except (ValueError, KeyError) as e:
            print("  (이전 결과를 못 읽었다, 새로 쓴다: %s)" % e)
    order = list(VARIANTS)
    merged = sorted(prior + results, key=lambda r: order.index(r["variant"])
                    if r["variant"] in order else len(order))
    payload = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "strategyId": STRATEGY_ID,
        "window": {"start": args.start, "end": args.end},
        "accounting": "monthly mark-to-market (pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm)",
        "results": merged,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("\n  -> %s" % args.out)


if __name__ == "__main__":
    main()
