#!/usr/bin/env python
"""PBR × ROE Quality Overlay OOS - PBR top-30 내 ROE quality gate 검증 (연구 샌드박스).

질문: 저PBR 신호(top-30, turnover20>=1억, 월별 리밸런싱)에 'ROE가 높은 종목만
남기는' quality gate를 overlay하면 value trap을 줄여 위험조정성과를 개선하는가.

설계 (MD: 02_pbr_roe_quality_overlay_oos_2026-09.md)
-----------------------------------------------------
- 먼저 기존 PBR top-30을 구성한다(pbr_value_v1과 동일: valuation-panel pbr,
  오름차순, turnover20>=1억 절대유동성).
- 그 안에서 ROE가 높은 종목만 남기는 gate 후보: 상위 100%(=PBR baseline),
  상위 70%, 상위 50%. ROE percentile 은 그 달 PBR top-30 내 ROE non-null
  종목집합의 pct-rank 기준. ROE 결측 종목은 게이트에서 제외(임의 대체 금지).
- gate 선택은 TRAIN에서만(기준: Sharpe). VALID/TEST는 TRAIN에서 선택된 gate를
  고정해 보고만 한다. TEST 결과로 gate를 다시 고르지 않는다.
- 금지: ROE 단독 전략을 승자로 해석하지 않는다. liquidity tercile gate 금지.
  production policy/config 변경 금지.

검증 5가지
----------
1. PBR baseline 대비 CAGR/Sharpe/MDD 개선
2. TEST 방향 유지
3. 2022년 집중도(연 수익·MDD·명목 보유 수) 변화
4. 종목 수 감소가 단순 표본 축소인지: gate와 같은 N의 PBR top-21/top-15
   (ROE 없이) control과 비교
5. ROE gate placebo: PBR top-30에서 gate가 제외한 것과 같은 수를 무작위로
   제외(gate와 별개 시드)해 gate 자체 효과를 분리

방법: 기존 엔진 재사용 - run_smoke(rule_module=...) + schedule_with_monthly_mtm
(월말 시가평가) + curve_metrics + split_snapshots + monthly_return_tstats.
production 정책 파일·엔진·selection.json은 수정하지 않는다(신규 파일만 생성).

  python run_pbr_roe_quality_overlay_oos.py [--placebo-seeds N] [--out DIR]
"""
import argparse
import json
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import run_pbr_topn_strength_oos as t1  # noqa: E402  (build_selection_for_topn, make_rule_module, split_snapshots, monthly_return_tstats 재사용)
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
ROE_PANEL = os.path.join(STRATEGY_LAB_DIR, "data", "factor-panel", "kr-monthly-v1.parquet")

START, END = "2016-01-01", "2026-08-14"
MIN_TURNOVER = 100_000_000.0
GATES = [1.0, 0.7, 0.5]          # 상위 100%(baseline) / 70% / 50%
NOMINAL_N = {1.0: 30, 0.7: 21, 0.5: 15}   # maxPositions: nominal gate size
SPLIT_FRACTIONS = {"TRAIN": 0.60, "VALID": 0.15, "TEST": 0.25}
SELECTION_METRIC = "sharpe"
EW_STRATEGY = "ew_benchmark_liquid_v1"

OUT_DIR_DEFAULT = os.path.join(STRATEGY_LAB_DIR, "reports", "2026-09-06-pbr-roe-quality-overlay")


def roe_lookup_from_panel(panel):
    """(ticker, date) -> roe. 가장 최근 과거일값(merge_asof 방식)으로 전달해
    패널에 없는 마지막 리밸런싱 달(2026-08-03)에 마지막 공개 ROE를 쓴다."""
    sub = panel[["ticker", "date", "roe"]].dropna(subset=["roe"]).copy()
    sub["date"] = sub["date"].astype(str)
    sub = sub.sort_values(["ticker", "date"])
    by_ticker = {}
    for ticker, g in sub.groupby("ticker"):
        by_ticker[ticker] = (g["date"].tolist(), g["roe"].tolist())
    lookup = {}

    def get(ticker, as_of):
        arr = by_ticker.get(ticker)
        if arr is None:
            return float("nan")
        dates, vals = arr
        import bisect
        i = bisect.bisect_right(dates, as_of) - 1
        return float(vals[i]) if i >= 0 else float("nan")

    lookup["get"] = get
    return lookup


def gate_selection(pbr30_selection, roe_get, gate_pct):
    """PBR top-30 selection dict를 gate_pct로 걸러 새 selection dict를 만든다.
    그 달 PBR top-30 내 ROE non-null 종목 pct-rank(높을수록 1.0) 기준
    rank >= 1-gate_pct 인 종목만 남긴다. gate_pct=1.0 은 전부 유지(baseline).
    월별 유지 개수와 ROE 결측 제외 개수를 함께 반환한다."""
    by_date = {}
    for ticker, entries in pbr30_selection.items():
        for e in entries:
            by_date.setdefault(e["date"], []).append((ticker, e))
    kept, dropped_missing = {}, 0
    monthly_counts = []
    for date in sorted(by_date):
        rows = by_date[date]
        scored = []
        for ticker, e in rows:
            r = roe_get(ticker, date)
            if not np.isnan(r):
                scored.append((r, ticker, e))
        if gate_pct >= 1.0:
            chosen = rows
        elif scored:
            s = pd.DataFrame([(r, t) for r, t, _ in scored], columns=["roe", "ticker"])
            s["rank"] = s["roe"].rank(pct=True, ascending=True)  # 높을수록 1.0
            keep_t = set(s.loc[s["rank"] >= 1 - gate_pct, "ticker"])
            chosen = [(t, e) for t, e in rows if t in keep_t]
        else:
            chosen = []
        dropped_missing += len(rows) - len(scored)
        monthly_counts.append(len(chosen))
        for ticker, e in chosen:
            kept.setdefault(ticker, []).append(dict(e))
    for ticker in kept:
        kept[ticker].sort(key=lambda e: e["date"])
    avg = (sum(monthly_counts) / len(monthly_counts)) if monthly_counts else None
    return kept, avg, dropped_missing


def measure(rule, params, start, end, tickers_selected):
    """run_smoke + MTM + 구간분할. (snapshots by split, full metrics) 반환."""
    base = run_smoke("pbr_roe_quality_overlay", start, end, REPO_ROOT,
                     rule_module=rule, ticker_subset=tickers_selected)
    resolved, bars_by_ticker, calendar = base["resolved"], base["bars_by_ticker"], base["calendar"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"],
        fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    portfolio, snapshots = schedule_with_monthly_mtm(
        resolved, portfolio_cfg, bars_by_ticker, calendar, start, end)
    by_split = t1.split_snapshots(snapshots)
    return portfolio, snapshots, by_split


def annual_return_and_mdd_2022(snapshots):
    """2022 calendar-year MTM 수익률과 2022 내 MDD(직전 연말부터 끝까지 구간).
    snapshots: [(date, equity)]. 없으면 (None, None)."""
    d2e = dict(snapshots)
    m2021 = max((d for d in d2e if d[:4] == "2021"), default=None)
    m2022 = max((d for d in d2e if d[:4] == "2022"), default=None)
    if not m2021 or not m2022:
        return None, None
    ann = d2e[m2022] / d2e[m2021] - 1.0
    sub = [(d, e) for d, e in snapshots if "2021-12" <= d[:7] <= "2022-12"]
    if len(sub) < 2:
        return round(float(ann), 4), None
    m = curve_metrics(sub)
    return round(float(ann), 4), m["mdd"]


def avg_selected_in_2022(selection):
    m2022 = [len([1 for e in v if e["date"].startswith("2022")]) for v in selection.values()]
    return round(float(np.mean(m2022)), 2) if m2022 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placebo-seeds", type=int, default=5)
    ap.add_argument("--out", default=OUT_DIR_DEFAULT)
    args = ap.parse_args()

    t0 = time.time()
    with open(PBR_POLICY, encoding="utf-8") as f:
        params = json.load(f)

    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = sorted(val["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-roe-quality-overlay-oos")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)", flush=True)

    rebalance_dates = t1.monthly_rebalance_dates(calendar, START, END)
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

    # --- 0) baseline + EW 실제 엔진 재현 ---
    print("\n=== baseline 재현: pbr_value_v1 / EW (실제 엔진) ===", flush=True)
    base = run_smoke("pbr_value_v1", START, END, REPO_ROOT)
    base_cfg = PortfolioConfig(
        initial_capital=base["params"]["portfolio"]["initialCapital"],
        max_positions=base["params"]["portfolio"]["maxPositions"],
        equal_weight=base["params"]["portfolio"]["equalWeight"],
        fractional_shares=base["params"]["portfolio"]["fractionalShares"],
        tie_break=base["params"]["portfolio"]["tieBreak"])
    bp, bsnaps = schedule_with_monthly_mtm(
        base["resolved"], base_cfg, base["bars_by_ticker"], base["calendar"], START, END)
    baseline_full = curve_metrics(bsnaps)
    print(f"  baseline full: {json.dumps(baseline_full)} closed={len(bp.closed_positions)}", flush=True)

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
    ew_by_split = t1.split_snapshots(ew_snaps_full)
    print(f"  EW full: {json.dumps(ew_full)} closed={len(ew_portfolio.closed_positions)}", flush=True)

    # --- 1) PBR top-30 selection (기존 build_selection.py와 동일 로직) ---
    pbr30_selection, avg30 = t1.build_selection_for_topn(
        val, bars_by_ticker, rebalance_dates, 30, hold_sessions_by_date)
    print(f"PBR top-30 selection: avgSelected/M={avg30} tickers={len(pbr30_selection)}", flush=True)

    # ROE lookup
    panel = pd.read_parquet(ROE_PANEL)
    roe_get = roe_lookup_from_panel(panel)["get"]

    # --- 2) gate variants + N-matched (표본 축소) controls ---
    variants = {}
    for g in GATES:
        sel, avg, dropped = gate_selection(pbr30_selection, roe_get, g)
        variants[f"gate{int(g*100)}"] = {
            "selection": sel, "avgSelected": avg, "roeMissingDropped": dropped,
            "maxPositions": NOMINAL_N[g], "gatePct": g}
        print(f"  gate {int(g*100)}%: avgSelected/M={avg} "
              f"(nominal {NOMINAL_N[g]}), ROE결측 제외 합계={dropped}", flush=True)

    for n in (21, 15):  # N-matched control: ROE 게이트 없이 PBR로만 같은 N
        sel, avg = t1.build_selection_for_topn(
            val, bars_by_ticker, rebalance_dates, n, hold_sessions_by_date)
        variants[f"pbrTop{n}"] = {
            "selection": sel, "avgSelected": avg, "roeMissingDropped": 0,
            "maxPositions": n, "gatePct": None}
        print(f"  PBR top-{n} (N-matched control): avgSelected/M={avg}", flush=True)

    # --- 3) 그리드 실행 ---
    print("\n=== 그리드 실행: TRAIN 선택 → VALID/TEST 고정 ===", flush=True)
    results = {}
    for name, v in variants.items():
        rule = t1.make_rule_module(params, v["selection"], v["maxPositions"])
        selected_tickers = sorted(set(v["selection"].keys()))
        portfolio, snaps_full, by_split = measure(
            rule, rule.PARAMS, START, END, selected_tickers)
        trades = [p for p in portfolio.closed_positions if "pnl" in p]
        wins = [p for p in trades if p["pnl"] > 0]
        win_rate = len(wins) / len(trades) if trades else None
        tstat_vs_ew = t1.monthly_return_tstats(snaps_full, ew_snaps_full)
        tstat_vs_zero = t1.monthly_return_tstats(snaps_full)
        ann2022, mdd2022 = annual_return_and_mdd_2022(snaps_full)
        split_metrics = {s: curve_metrics(sn) for s, sn in by_split.items()}
        results[name] = {
            "variant": name, "gatePct": v["gatePct"],
            "maxPositions": rule.PARAMS["portfolio"]["maxPositions"],
            "avgSelectedPerMonth": v["avgSelected"],
            "roeMissingDroppedTotal": v["roeMissingDropped"],
            "tickersEverSelected": len(selected_tickers),
            "closedPositionCount": len(trades),
            "winRate": round(float(win_rate), 4) if win_rate is not None else None,
            "fullPeriod": curve_metrics(snaps_full),
            "bySplit": split_metrics,
            "tstatVsZeroFull": tstat_vs_zero,
            "tstatVsEWFull": tstat_vs_ew,
            "year2022_return": ann2022,
            "year2022_mdd": mdd2022,
            "avgSelected2022": avg_selected_in_2022(v["selection"]),
        }
        print(f"  {name}: TRAIN={split_metrics['TRAIN']['sharpe']} "
              f"VALID={split_metrics['VALID']['sharpe']} "
              f"TEST={split_metrics['TEST']['sharpe']} | "
              f"full={curve_metrics(snaps_full)['cagr']}/{curve_metrics(snaps_full)['sharpe']} "
              f"closed={len(trades)} ({time.time()-t0:.0f}s)", flush=True)

    # --- 4) TRAIN에서만 gate 선택 ---
    gate_names = [f"gate{int(g*100)}" for g in GATES]
    train_selected = max(
        gate_names, key=lambda n: results[n]["bySplit"]["TRAIN"][SELECTION_METRIC] or -999)
    rank_by = {}
    for split_name in ("TRAIN", "VALID", "TEST"):
        order = sorted(gate_names,
                       key=lambda n: (results[n]["bySplit"][split_name]["sharpe"] is None,
                                      results[n]["bySplit"][split_name]["sharpe"] or -999),
                       reverse=True)
        rank_by[split_name] = {n: i + 1 for i, n in enumerate(order)}
    print(f"\nTRAIN에서 선택된 gate (기준=Sharpe): {train_selected}")
    print("gate 순위:", {s: r for s, r in rank_by.items()})

    # --- 5) placebo: 선택된 gate의 제외 수를 무작위로 (ROE 무시) ---
    sel_pct = results[train_selected]["gatePct"]
    placebo = {}
    for seed in range(args.placebo_seeds):
        rng = random.Random(1000 + seed)
        psel = {}
        p_counts = []
        for date, rows in _selection_by_date(pbr30_selection).items():
            n_keep = max(1, int(round(sel_pct * len(rows))))
            chosen_t = set(rng.sample([t for t, _ in rows], min(n_keep, len(rows))))
            p_counts.append(len(chosen_t))
            for t, e in rows:
                if t in chosen_t:
                    psel.setdefault(t, []).append(dict(e))
        for t in psel:
            psel[t].sort(key=lambda e: e["date"])
        rule = t1.make_rule_module(params, psel, NOMINAL_N[sel_pct])
        selected_tickers = sorted(set(psel.keys()))
        portfolio, snaps_full, by_split = measure(
            rule, rule.PARAMS, START, END, selected_tickers)
        placebo[seed] = {
            "avgSelected": round(float(np.mean(p_counts)), 2) if p_counts else None,
            "fullPeriod": curve_metrics(snaps_full),
            "bySplit": {s: curve_metrics(sn) for s, sn in by_split.items()},
        }
        print(f"  placebo seed={seed}: TRAIN={placebo[seed]['bySplit']['TRAIN']['sharpe']} "
              f"VALID={placebo[seed]['bySplit']['VALID']['sharpe']} "
              f"TEST={placebo[seed]['bySplit']['TEST']['sharpe']}")  # , flush=True

    summary = {
        "question": "Does a high-ROE overlay inside PBR top-30 reduce value traps / improve risk-adjusted perf?",
        "track": "KR",
        "start": START, "end": END,
        "method": "engine.runner.run_smoke(rule_module=...) + monthly MTM; PBR top-30(turnover20>=1e8, "
                  "ascending pbr) inside-gate by ROE pct-rank(top 100/70/50%); TRAIN Sharpe selects gate, "
                  "VALID/TEST fixed; N-matched PBR top-21/15 controls; ROE-missing excluded (no imputation).",
        "selectionMetric": SELECTION_METRIC,
        "trainSelectedGate": train_selected,
        "gateRankBySplit": rank_by,
        "baselinePBR_full": baseline_full,
        "baselinePBR_closed": len(bp.closed_positions),
        "ewBenchmark_full": ew_full,
        "ewBenchmark_bySplit": {k: curve_metrics(v) for k, v in ew_by_split.items()},
        "variants": results,
        "placebo": placebo,
        "placeboSeeds": args.placebo_seeds,
    }

    os.makedirs(args.out, exist_ok=True)
    out_path = os.path.join(args.out, "pbr-roe-quality-overlay-oos.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PBR×ROE quality overlay OOS. TRAIN(2016-01~2022-05) gate 선택 → "
                       "VALID/TEST 고정. production 정책/엔진 무변경. MTM 회계. 판정은 하지 않는다.",
            "roeSource": "factor-panel kr-monthly-v1 (manifest source=quality-panel, PIT-safe)",
            "summary": summary,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)

    print("\n=== 결과 요약 ===")
    print(f"baseline PBR full: {json.dumps(baseline_full)}")
    print(f"EW full: {json.dumps(ew_full)}")
    print(f"TRAIN 선택 gate = {train_selected}")
    hdr = f"{'variant':<10}{'TRAIN':>8}{'VALID':>8}{'TEST':>8}{'fullCAGR':>9}{'fullMDD':>9}{'winRate':>8}{'N':>7}"
    print(hdr)
    for name in [f"gate{int(g*100)}" for g in GATES] + ["pbrTop21", "pbrTop15"]:
        r = results[name]
        print(f"{name:<10}{r['bySplit']['TRAIN']['sharpe']:>8.3f}"
              f"{r['bySplit']['VALID']['sharpe']:>8.3f}"
              f"{r['bySplit']['TEST']['sharpe']:>8.3f}"
              f"{r['fullPeriod']['cagr']:>9.4f}"
              f"{r['fullPeriod']['mdd']:>9.4f}"
              f"{(r['winRate'] or 0):>8.4f}"
              f"{r['closedPositionCount']:>7d}")


def _selection_by_date(pbr30_selection):
    by = {}
    for ticker, entries in pbr30_selection.items():
        for e in entries:
            by.setdefault(e["date"], []).append((ticker, e))
    return by


if __name__ == "__main__":
    main()