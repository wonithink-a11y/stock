#!/usr/bin/env python
"""Low-vol(rv60) 단독 long-only — decile vs top-30, 엔진 MTM OOS.

독립 실험 05_lowvol_factor_oos 의 최소 비교를 실제 엔진으로 잰다:
  1. Low-vol 단독 decile/long-only  -> factor_rv60_v1        (기존)
  2. Low-vol top-30 portfolio         -> factor_rv60_v1_top30  (신규, 같은 A4 파이프라인)
벤치마크 = ew_benchmark_liquid_v1.

방법: run_smoke 를 2016-01-01~2026-08-14 전체에 1번 돌리고(파라미터 고정),
월별 시가평가(MTM) 곡선을 TRAIN/VALID/TEST 로 잘라 구간 지표를 낸다.
실현손익 누적 회계는 프로젝트에서 폐기됨(2026-08-22) - 반드시 MTM 을 쓴다.

t-stat: 프로젝트 관례(lesson: 절대수익 t 는 바닥선이 죽는다)대로
월별 초과수익(전략 MTM 월수익 - EW 벤치 MTM 월수익)으로 계산한다.
win_rate·N: 그 구간에 진입·청산된 포지션(closed) 기준 trade_stats.

  python run_lowvol_oos.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from engine.metrics.metrics import trade_stats  # noqa: E402
from pbr_vs_ew_monthly_mtm import (  # noqa: E402 — 검증된 MTM 로직 재사용
    schedule_with_monthly_mtm, curve_metrics, START, END, REPO_ROOT)

DECILE = "factor_rv60_v1"
TOP30 = "factor_rv60_v1_top30"
BENCHMARK = "ew_benchmark_liquid_v1"
STRATEGIES = [DECILE, TOP30]
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


def monthly_returns(snaps, lo, hi):
    """구간 내 (date, equity) 스냅샷에서 월수익률 배열을 뽑는다."""
    seg = [(d, v) for d, v in snaps if lo <= d <= hi]
    return seg, np.array([seg[i][1] / seg[i - 1][1] - 1 for i in range(1, len(seg))], dtype=float)


def closed_trades_in(portfolio, lo, hi):
    trades = []
    for p in portfolio.closed_positions:
        if lo <= p["entry_date"] <= hi:
            trades.append({"pnl": p["pnl"], "holding_sessions": 1, "entry_date": p["entry_date"]})
    return trades


def max_year_pct_excess(excess, seg):
    """초과수익 최대 단일연도 비중 - PBR 원본(전체 초과의 98.6% 단일연도) 사고 방지."""
    tot = float(excess.sum())
    if tot <= 0:
        return None
    by = {}
    for i, (d, _) in enumerate(seg[1:], start=1):
        y = d[:4]
        by[y] = by.get(y, 0.0) + excess[i - 1]
    return round(100.0 * max(by.values()) / tot, 1)


def trade_win_rate(trades):
    wins = [t for t in trades if t["pnl"] > 0]
    return round(100.0 * len(wins) / len(trades), 1) if trades else None


def run():
    snaps, portfolios = {}, {}
    for sid in STRATEGIES + [BENCHMARK]:
        snaps[sid], portfolios[sid] = measure(sid)

    def align_excess(strategy_snaps, bench_snaps, lo, hi):
        s3, sret = monthly_returns(strategy_snaps, lo, hi)
        b3, bret = monthly_returns(bench_snaps, lo, hi)
        if len(sret) != len(bret):
            return None, None, None
        excess = sret - bret
        return excess, s3, bret

    out = {}
    for sid in STRATEGIES:
        out[sid] = {"overall": curve_metrics(snaps[sid]),
                    "overallTrades": {},
                    "byPeriod": {}}
        portfolio = portfolios[sid]
        ts_all = trade_stats([{"pnl": p["pnl"], "holding_sessions": 1}
                              for p in portfolio.closed_positions])
        out[sid]["overallTrades"] = {
            "winRate": round(ts_all["winRate"] * 100, 1) if ts_all.get("winRate") is not None else None,
            "n": ts_all["tradeCount"]}
        # 전체 기간 월별 초과수익 t (프로젝트 관례: EW 대비 초과 기준)
        e, _s3, _b3 = align_excess(snaps[sid], snaps[BENCHMARK], START, END)
        if e is not None and len(e) > 1:
            esd = float(e.std(ddof=1))
            out[sid]["overall"]["tExcess"] = (
                round(float(e.mean() / (esd / np.sqrt(len(e)))), 3) if esd > 0 else 0.0)
            out[sid]["overall"]["meanMonthlyExcess"] = round(float(e.mean()), 6)
            out[sid]["overall"]["excessHitRate"] = round(float((e > 0).mean()), 3)
            out[sid]["overall"]["nMonths"] = len(e)
        for name, lo, hi in PERIODS:
            seg, rets = monthly_returns(snaps[sid], lo, hi)
            if len(seg) < 3:
                out[sid]["byPeriod"][name] = None
                continue
            m = curve_metrics(seg)
            m["nMonths"] = len(seg)
            m["meanMonthly"] = round(float(rets.mean()), 6)
            trades = closed_trades_in(portfolio, lo, hi)
            ts = trade_stats(trades)
            m["winRate"] = round(ts["winRate"] * 100, 1) if ts.get("winRate") is not None else None
            m["n"] = ts["tradeCount"]
            excess, seg2, _bret = align_excess(snaps[sid], snaps[BENCHMARK], lo, hi)
            m["tExcess"] = None
            m["meanMonthlyExcess"] = None
            m["excessHitRate"] = None
            m["maxYearPctExcess"] = None
            if excess is not None and len(excess) > 1:
                esd = float(excess.std(ddof=1))
                m["tExcess"] = round(float(excess.mean() / (esd / np.sqrt(len(excess)))), 3) if esd > 0 else 0.0
                m["meanMonthlyExcess"] = round(float(excess.mean()), 6)
                m["excessHitRate"] = round(float((excess > 0).mean()), 3)
                m["maxYearPctExcess"] = max_year_pct_excess(excess, seg2)
            out[sid]["byPeriod"][name] = m
        print(f"  {sid} 지표 계산 완료", flush=True)

    bench = {"overall": curve_metrics(snaps[BENCHMARK]),
             "byPeriod": {name: curve_metrics([(d, v) for d, v in snaps[BENCHMARK] if lo <= d <= hi])
                          for name, lo, hi in PERIODS}}
    return snaps, out, bench


def main():
    t0 = time.time()
    snaps, out, bench = run()
    bench_overall, bench_by = bench["overall"], bench["byPeriod"]

    print(f"\n=== Low-vol OOS (엔진 MTM, {START} ~ {END}) ===")
    for sid in STRATEGIES:
        o = out[sid]['overall']
        ot = out[sid]['overallTrades']
        t_ex = o.get('tExcess')
        t_s = "" if t_ex is None else f"{t_ex:+.2f}"
        wr = "" if ot['winRate'] is None else f"{ot['winRate']:.1f}%"
        print(f"\n[{sid}] 전체: CAGR {o['cagr'] * 100:+.2f}% MDD {o['mdd'] * 100:.1f}% "
              f"Sharpe {o['sharpe']:.2f} 승률 {wr} N {ot['n']} t(초과) {t_s}")
        print(f"{'구간':<7}{'개월':>5}{'CAGR':>9}{'MDD':>9}{'Sharpe':>8}{'승률':>7}{'N':>6}"
              f"{'t(초과)':>9}{'월초과':>9}")
        for name, _, _ in PERIODS:
            blk = out[sid]["byPeriod"][name]
            if blk is None:
                continue
            t_ = "" if blk["tExcess"] is None else f"{blk['tExcess']:>8.2f}"
            wr = "" if blk["winRate"] is None else f"{blk['winRate']:>6.1f}%"
            ex = "" if blk["meanMonthlyExcess"] is None else f"{blk['meanMonthlyExcess'] * 100:>+7.2f}%"
            print(f"{name:<7}{blk['nMonths']:>5}{blk['cagr'] * 100:>+8.2f}%"
                  f"{blk['mdd'] * 100:>8.1f}%{blk['sharpe']:>8.2f}{wr:>7}"
                  f"{blk['n']:>6}{t_:>9}{ex:>9}")
        print(f"(벤치마크 전체: CAGR {bench_overall['cagr'] * 100:+.2f}% "
              f"MDD {bench_overall['mdd'] * 100:.1f}% Sharpe {bench_overall['sharpe']:.2f})")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                           f"{time.strftime('%Y-%m-%d')}-lowvol-factor-oos-mtm")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "mtm.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"method": "monthly mark-to-market equity curve "
                             "(pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm 재사용)",
                   "period": f"{START} ~ {END}",
                   "benchmark": BENCHMARK,
                   "note": "실현손익 누적 방식은 2026-08-22 에 폐기됨. "
                           "tExcess = EW 벤치마크 대비 월별 초과수익 t-stat(프로젝트 관례)."
                           " winRate/N = 구간 내 진입·청산된 closed 포지션 기준.",
                   "results": out}, f, ensure_ascii=False, indent=2, default=str)
    print(f"저장: {path}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()