#!/usr/bin/env python
"""PBR top-N 강도 실험 - TRAIN 선택 → VALID/TEST 고정 (연구 샌드박스).

질문: 기존 PBR 신호(저PBR, turnover20>=1억, 월별 리밸런싱)에서 '얼마나 강한
PBR 상위집합을 보유해야 하는가' - topN ∈ {10, 20, 30, 50, 100} 중 어느 것이
최선인가. 전체기간 성과를 보고 사후 선택하지 않고 TRAIN 구간에서만 선택한 뒤
VALID/TEST는 그 선택을 고정해 보고만 한다.

방법: 기존 Strategy Lab 엔진과 정본 데이터/패널을 그대로 재사용한다.
  - build_selection.py(전략 폴더)와 같은 오프라인 선택 로직: valuation-panel에서
    pbr, a2a bars에서 turnover20>=1억 계산 → 그 달 PBR 오름차순 상위 N개.
  - rule_module 인메모리 생성(engine.runner.run_smoke(rule_module=...),
    run_pbr_combined_oos_validation.py와 같은 패턴) - production policy.json
    미변경, 신규 파일만 생성.
  - 회계: pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm (월말 시가평가 MTM).
  - 구간: 월별 스냅샷을 시간순 60/15/25%로 자른 TRAIN/VALID/TEST.
  - 선택 기준: TRAIN Sharpe. VALID/TEST는 고정된 그 topN을 보고만 한다.
  - 비교군: 동일 조건 EW 벤치마크(ew_benchmark_liquid_v1) + 기존 PBR baseline(topN=30).

production/config/scripts/lib/data는 건드리지 않는다. 결과는 findings/에만 쓴다.

  python run_pbr_topn_strength_oos.py
"""
import json
import math
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import run_smoke, _drop_suspension_rows  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm, curve_metrics  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRATEGY_LAB_DIR = os.path.dirname(os.path.abspath(__file__))
PBR_POLICY = os.path.join(STRATEGY_LAB_DIR, "strategies", "pbr_value_v1", "policy.json")
VALUATION_PANEL = os.path.join(STRATEGY_LAB_DIR, "reports", "2026-08-21-a5-valuation-precheck",
                               "valuation-panel.jsonl")

START, END = "2016-01-01", "2026-08-14"
MIN_TURNOVER = 100_000_000.0
TOP_N_GRID = [10, 20, 30, 50, 100]
BASELINE_TOP_N = 30
EW_STRATEGY = "ew_benchmark_liquid_v1"
SPLIT_FRACTIONS = {"TRAIN": 0.60, "VALID": 0.15, "TEST": 0.25}
SELECTION_METRIC = "sharpe"

# findings 파일명 관련 (실행 시점에 오늘 날짜를 붙인다)
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports", "2026-09-06-pbr-topn-strength-oos")


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def make_rule_module(params, selection_by_ticker, max_positions):
    """run_pbr_combined_oos_validation.py와 같은 인메모리 rule 모듈 생성.
    max_positions를 topN 이상으로 덮어써 포트폴리오 트렁케이션을 막는다
    (엔진 구조상 각 후보의 최대 보유 수는 그 topN - 공정 비교를 위해
    maxPositions >= topN로 설정)."""
    p = dict(params)
    p["portfolio"] = dict(params["portfolio"])
    p["portfolio"]["maxPositions"] = max_positions

    hold_col = "pbrHoldSessions"
    fallback_max_holding = params["risk"]["maxHoldingSessions"]
    reward_risk = params["risk"]["rewardRisk"]
    stop_multiple = 100.0
    selection = {t: {e["date"]: e["holdSessions"] for e in entries}
                 for t, entries in selection_by_ticker.items()}

    def compute_features(bars):
        features = bars.copy()
        features[hold_col] = float("nan")
        return features

    def generate_signals(symbol, features):
        from engine.signals.schema import Signal
        dates = selection.get(symbol, {})
        out = []
        for d, hold_sessions in dates.items():
            ts = pd.Timestamp(d)
            if ts in features.index:
                features.loc[ts, hold_col] = hold_sessions
                out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
        return out

    def risk_spec_for(features_row):
        from engine.signals.schema import RiskSpec
        close = float(features_row["close"])
        huge_stop_distance = close * stop_multiple
        hold = features_row.get(hold_col)
        max_holding = int(hold) if hold is not None and not pd.isna(hold) else fallback_max_holding
        return RiskSpec(stop_distance=huge_stop_distance, reward_risk=reward_risk,
                        max_holding_sessions=max_holding)

    return types.SimpleNamespace(
        PARAMS=p, compute_features=compute_features,
        generate_signals=generate_signals, risk_spec_for=risk_spec_for)


def split_snapshots(snapshots, fractions=SPLIT_FRACTIONS):
    """월별 스냅샷을 시간순 60/15/25%로 자른다. 각 구간 t0=그 구간 첫 스냅샷
    자기 자신(그 구간 자체의 등락만 본다)."""
    n = len(snapshots)
    n_train = int(round(n * fractions["TRAIN"]))
    n_valid = int(round(n * fractions["VALID"]))
    return {
        "TRAIN": snapshots[:n_train + 1],
        "VALID": snapshots[n_train:n_train + n_valid + 1],
        "TEST": snapshots[n_train + n_valid:],
    }


def monthly_return_tstats(snapshots, benchmark_snapshots=None):
    """월별 MTM 수익률의 t-통계량. benchmark_snapshots를 주면 초과수익(전략 -
    벤치마크 같은 달) 기준, 없으면 자기 수익률 평균의 0 대비 t.
    반환: {'tstat': float, 'meanMonthly': float, 'nMonths': int}"""
    m1 = {d: e for d, e in snapshots}
    dates = sorted(m1)
    rets = []
    for i in range(1, len(dates)):
        prev = m1[dates[i - 1]]
        if prev > 0:
            rets.append(m1[dates[i]] / prev - 1)
    if benchmark_snapshots is not None:
        m2 = {d: e for d, e in benchmark_snapshots}
        brets = []
        for i in range(1, len(dates)):
            d_prev, d_cur = dates[i - 1], dates[i]
            if d_cur in m2 and d_prev in m2 and m2[d_prev] > 0:
                brets.append(m2[d_cur] / m2[d_prev] - 1)
        if len(brets) < len(rets):
            # 벤치마크가 짧으면 앞쪽 전략 수익률도 잘라 맞춘다
            rets = rets[len(rets) - len(brets):]
        arr = np.array(rets) - np.array(brets)
    else:
        arr = np.array(rets)
    n = len(arr)
    if n < 2 or arr.std(ddof=1) == 0:
        return {"tstat": None, "meanMonthly": None, "nMonths": n}
    t = arr.mean() / (arr.std(ddof=1) / math.sqrt(n))
    return {"tstat": round(float(t), 4), "meanMonthly": round(float(arr.mean()), 6), "nMonths": n}


def build_selection_for_topn(val, bars_by_ticker, rebalance_dates, top_n, hold_sessions_by_date):
    """build_selection.py와 동일한 선택 로직. (topN짜리 selection_by_ticker dict) 반환."""
    turnover_rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        close, vol = bars["close"], bars["volume"]
        idx = close.index.astype(str)
        turnover20 = (close * vol).rolling(20).mean()
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            i = pos.get(t)
            if i is None:
                continue
            tv = turnover20.iloc[i]
            if pd.isna(tv):
                continue
            turnover_rows.append({"ticker": ticker, "asOf": t, "turnover20": float(tv)})
    turnover_df = pd.DataFrame(turnover_rows)

    merged = val.merge(turnover_df, on=["ticker", "asOf"], how="inner")
    eligible = merged[merged["turnover20"] >= MIN_TURNOVER]

    selection = {}
    monthly_counts = []
    for asOf, g in eligible.groupby("asOf"):
        if asOf not in hold_sessions_by_date:
            continue
        top = g.sort_values("pbr", ascending=True).head(top_n)
        monthly_counts.append(len(top))
        for rank, ticker in enumerate(top["ticker"]):
            selection.setdefault(ticker, []).append(
                {"date": asOf, "holdSessions": hold_sessions_by_date[asOf], "rank": rank})
    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])
    return selection, (sum(monthly_counts) / len(monthly_counts)) if monthly_counts else None


def measure(rule, params, start, end, tickers_selected):
    """run_smoke + MTM + 구간분할. (snapshots by split, full metrics, portfolio) 반환."""
    base = run_smoke("pbr_topn_strength", start, end, REPO_ROOT, rule_module=rule,
                     ticker_subset=tickers_selected)
    resolved, bars_by_ticker, calendar = base["resolved"], base["bars_by_ticker"], base["calendar"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"],
        fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snapshots = schedule_with_monthly_mtm(
        resolved, portfolio_cfg, bars_by_ticker, calendar, start, end)
    by_split = split_snapshots(snapshots)
    return portfolio, snapshots, by_split


def main():
    t0 = time.time()
    with open(PBR_POLICY, encoding="utf-8") as f:
        params = json.load(f)

    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = sorted(val["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-topn-strength-oos")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    hold_sessions_by_date = {}
    for k, t in enumerate(rebalance_dates[:-1]):
        entry_date = calendar.next_session(t)
        next_rebal = rebalance_dates[k + 1]
        exit_target = calendar.next_session(next_rebal)
        if entry_date is None or exit_target is None:
            continue
        hold_sessions_by_date[t] = len(calendar.sessions_between(entry_date, exit_target))
    if rebalance_dates:
        hold_sessions_by_date.setdefault(rebalance_dates[-1], 21)

    # --- 1) PBR baseline(topN=30)을 실제 엔진 그대로 재현 (사전 고정 검증) ---
    print("\n=== baseline 재현: pbr_value_v1 (topN=30, 실제 엔진) ===")
    base = run_smoke("pbr_value_v1", START, END, REPO_ROOT)
    base_cfg = PortfolioConfig(
        initial_capital=base["params"]["portfolio"]["initialCapital"],
        max_positions=base["params"]["portfolio"]["maxPositions"],
        equal_weight=base["params"]["portfolio"]["equalWeight"],
        fractional_shares=base["params"]["portfolio"]["fractionalShares"],
        tie_break=base["params"]["portfolio"]["tieBreak"])
    bp, bsnaps = schedule_with_monthly_mtm(
        base["resolved"], base_cfg, base["bars_by_ticker"], base["calendar"], START, END)
    bfull = curve_metrics(bsnaps)
    print(f"  baseline MTM full: {json.dumps(bfull)} closed={len(bp.closed_positions)}")
    baseline_full = bfull

    # --- 2) EW 벤치마크 (비교군, 실제 엔진) ---
    print("\n=== EW 벤치마크 재현: ew_benchmark_liquid_v1 (실제 엔진) ===")
    ew_base = run_smoke(EW_STRATEGY, START, END, REPO_ROOT)
    ew_cfg = PortfolioConfig(
        initial_capital=ew_base["params"]["portfolio"]["initialCapital"],
        max_positions=ew_base["params"]["portfolio"]["maxPositions"],
        equal_weight=ew_base["params"]["portfolio"]["equalWeight"],
        fractional_shares=ew_base["params"]["portfolio"]["fractionalShares"],
        tie_break=ew_base["params"]["portfolio"]["tieBreak"])
    ew_portfolio, ew_snaps_full = schedule_with_monthly_mtm(
        ew_base["resolved"], ew_cfg, ew_base["bars_by_ticker"], ew_base["calendar"], START, END)
    ew_full = curve_metrics(ew_snaps_full)
    print(f"  EW full: {json.dumps(ew_full)} closed={len(ew_portfolio.closed_positions)}")
    ew_by_split = split_snapshots(ew_snaps_full)

    # --- 3) topN 그리드 실험 (같은 인메모리 선택 로직으로 공정 비교) ---
    print("\n=== topN 그리드: TRAIN 선택 → VALID/TEST 고정 ===")
    all_selections = {}
    for top_n in TOP_N_GRID:
        selection, avg = build_selection_for_topn(
            val, bars_by_ticker, rebalance_dates, top_n, hold_sessions_by_date)
        all_selections[top_n] = (selection, avg)
        n_ticks = len({t for t, e in selection.items() for e in e})
        print(f"  selection topN={top_n}: avgSelected/M={avg}, tickersEverSelected={n_ticks}")

    grid = {}
    for top_n in TOP_N_GRID:
        selection, _ = all_selections[top_n]
        max_pos = max(top_n, 1)
        rule = make_rule_module(params, selection, max_pos)
        selected_tickers = sorted(set(selection.keys()))
        portfolio, snaps_full, by_split = measure(rule, rule.PARAMS, START, END, selected_tickers)

        # WINRATE / N(클로즈드 트레이드 수) / T-STAT
        trades = [p for p in portfolio.closed_positions if "pnl" in p]
        wins = [p for p in trades if p["pnl"] > 0]
        win_rate = len(wins) / len(trades) if trades else None
        tstat_vs_ew = monthly_return_tstats(snaps_full, ew_snaps_full)
        tstat_vs_zero = monthly_return_tstats(snaps_full)

        split_metrics = {name: curve_metrics(snaps) for name, snaps in by_split.items()}
        grid[top_n] = {
            "topN": top_n,
            "maxPositions": rule.PARAMS["portfolio"]["maxPositions"],
            "avgSelectedPerMonth": all_selections[top_n][1],
            "tickersEverSelected": len(selected_tickers),
            "closedPositionCount": len(trades),
            "winRate": round(float(win_rate), 4) if win_rate is not None else None,
            "fullPeriod": curve_metrics(snaps_full),
            "bySplit": split_metrics,
            "tstatVsZeroFull": tstat_vs_zero,
            "tstatVsEWFull": tstat_vs_ew,
        }
        print(f"  topN={top_n}: "
              f"TRAIN sharpe={split_metrics['TRAIN']['sharpe']} "
              f"VALID sharpe={split_metrics['VALID']['sharpe']} "
              f"TEST sharpe={split_metrics['TEST']['sharpe']} | "
              f"full CAGR={grid[top_n]['fullPeriod']['cagr']} "
              f"closed={len(trades)} winRate={grid[top_n]['winRate']} "
              f"tstatVsEW={tstat_vs_ew['tstat']} ({time.time()-t0:.0f}s)")

    # --- 4) TRAIN에서만 선택 → VALID/TEST 고정 ---
    train_ranked = sorted(
        grid.items(),
        key=lambda kv: (grid[kv[0]]["bySplit"]["TRAIN"][SELECTION_METRIC] is None,
                        grid[kv[0]]["bySplit"]["TRAIN"][SELECTION_METRIC] or -999),
        reverse=True)
    train_best_topn = train_ranked[0][0]

    print(f"\nTRAIN에서 선택된 best topN (기준=Sharpe): {train_best_topn}")
    print("TRAIN 순위(작은 topN부터 Sharpe 내림차순):",
          [t[0] for t in train_ranked])

    # 순위 유지 여부: TRAIN 순위 vs VALID/TEST 순위 (각 구간 Sharpe 순서)
    rank_by = {}
    for split_name in ("TRAIN", "VALID", "TEST"):
        order = sorted(grid.keys(), key=lambda n: (grid[n]["bySplit"][split_name]["sharpe"] is None,
                                                   grid[n]["bySplit"][split_name]["sharpe"] or -999),
                       reverse=True)
        rank_by[split_name] = {n: i + 1 for i, n in enumerate(order)}
        print(f"  {split_name} Sharpe 순위: {order}")

    train_best = grid[train_best_topn]

    summary = {
        "question": "how strong a top-N PBR subset to hold",
        "track": "KR",
        "start": START, "end": END,
        "method": "engine.runner.run_smoke(rule_module=...) + monthly MTM, "
                  "selection built inline (build_selection.py logic), 60/15/25 TRAIN/VALID/TEST split",
        "selectionMetric": SELECTION_METRIC,
        "trainSelectedTopN": train_best_topn,
        "baselineTopN": BASELINE_TOP_N,
        "baselinePBR_full": baseline_full,
        "ewBenchmark_full": ew_full,
        "ewBenchmark_bySplit": {k: curve_metrics(v) for k, v in ew_by_split.items()},
        "trainRankBySplit": rank_by,
        "grid": grid,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "pbr-topn-strength-oos.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PBR top-N 강도 실험(TRAIN 선택→VALID/TEST 고정). production 정책 무변경, "
                       "엔진/데이터 재사용, MTM 회계. 판정은 하지 않는다.",
            "summary": summary,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)

    print("\n=== 결과 요약 ===")
    print(f"baseline PBR(topN=30) full: {json.dumps(baseline_full)}")
    print(f"EW benchmark full: {json.dumps(ew_full)}")
    print(f"TRAIN best topN = {train_best_topn}")
    for n in TOP_N_GRID:
        g = grid[n]
        print(f"topN={n}: TRAIN={g['bySplit']['TRAIN']['sharpe']} "
              f"VALID={g['bySplit']['VALID']['sharpe']} "
              f"TEST={g['bySplit']['TEST']['sharpe']} "
              f"fullCAGR={g['fullPeriod']['cagr']} winRate={g['winRate']} "
              f"N={g['closedPositionCount']} tstatVsEW={g['tstatVsEWFull']['tstat']}")


if __name__ == "__main__":
    main()
