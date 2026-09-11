#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""연구 후보(KEEP/HOLD) 전략이 **실제 한국 시장 지수**를 비용 차감 후에도
초과했는가 - 단일 질문에 답하는 비교 실험. 새 팩터·파라미터를 만들지 않는다.

핵심 규칙(이 스크립트가 지키는 것):
  1. 회계는 정본 MTM 하나뿐이다 - `pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm`
     을 그대로 import 한다. 실현손익 누적(`eq += pnl`)은 쓰지 않는다.
  2. 전략 정의(유니버스·리밸런싱·보유기간·비용·PIT)는 각 strategies/*/policy.json
     을 그대로 읽는다. 재최적화 없음. factor_earnings_yield_v1 만 동결본
     **policy_30.json** 을 쓴다 - 2026-09-04 에 build_factor_selection.py 가
     policy.json 을 mp=200 으로 덮어쓴 적이 있어 앵커를 따로 둔 것이다.
     ★ 그 드리프트는 2026-09-08(`bcc999c`)에 mp=30 으로 복구됐다. 그래서 이
     스크립트의 옛 "mp=200" 비교 행은 지웠다 - 지금 돌리면 같은 설정을 다른
     이름으로 두 번 재게 된다. mp=200 실측치는 findings/market-benchmark-
     comparison-2026-09.md 에 그대로 남아 있다(그때는 진짜 mp=200 이었다).
  3. 비용은 전 전략 동일하게 policy.json 값(왕복 30bp, 슬리피지 0). 지수
     벤치마크에도 같은 진입/청산 15bp 를 1회씩 물린다(바이앤홀드 1회 왕복).
  4. 계산하지 않은 값은 None 으로 남긴다. 추정·0·N/A 로 채우지 않는다.

  python market_comparison_kr_2026_09.py --curves      # 엔진 실행(느림, ~25분)
  python market_comparison_kr_2026_09.py --analyze     # 지표 계산(빠름)
  python market_comparison_kr_2026_09.py --selftest
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import (  # noqa: E402  - 정본 MTM 경로, 로직 복제 금지
    schedule_with_monthly_mtm, curve_metrics, annual_returns_mtm)

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
OUT_DIR = os.path.join(LAB, "reports", "2026-09-06-market-comparison")
CURVES_PATH = os.path.join(OUT_DIR, "curves.json")
RESULT_PATH = os.path.join(OUT_DIR, "market-comparison.json")

START, END = "2016-01-01", "2026-08-14"           # pbr_vs_ew_monthly_mtm 와 동일
LAST_FULL_YEAR_END = "2025-12-31"                 # 부분연도(2026) 배제용 절단점
ENTRY_BPS, EXIT_BPS = 15, 15                      # 전 전략 policy.json 공통값

KOSPI_PATH = os.path.join(LAB, "data", "market-regime", "krkospi_raw.parquet")
KOSDAQ_PATH = os.path.join(LAB, "data", "market-regime", "krkosdaq_raw.parquet")

# (strategy_id, 라벨, repo 상태, policy 파일, 이 상태의 근거 findings)
# 상태는 committed findings frontmatter 의 verdict 를 그대로 옮긴 것이다.
CANDIDATES = [
    ("pbr_value_v1", "PBR baseline", "REFERENCE", "policy.json",
     "pbr-dropout-maxexcl-combined-2026-08.md (baseline 열)"),
    ("pbr_value_v1_dropout", "PBR +dropout", "HOLD", "policy.json",
     "pbr-dropout-turnover-limit-2026-08.md"),
    ("pbr_value_v1_maxexcl", "PBR +MAX제외", "HOLD", "policy.json",
     "pbr-max-exclusion-2026-08.md"),
    ("pbr_value_v1_combined", "PBR combined", "KEEP", "policy.json",
     "pbr-combined-oos-validation-2026-08.md (KEEP) / pbr-dropout-maxexcl-combined (HOLD)"),
    ("pbr_value_v1_sizing", "PBR +금리사이징", "HOLD", "policy.json",
     "pbr-sizing-macro-continuous-2026-08.md"),
    # 2026-08-24 엔진검증은 HOLD 였으나 2026-09-04 lowmom60-test-negative-regime-
    # diagnosis 가 REJECT 로 내렸다(registry 는 2026-08-31 스냅샷이라 이걸 모른다).
    # 후보 집합에서는 빠지지만 모의계좌에 아직 살아 있어(사용자 결정) 같이 잰다.
    ("lowmom60_v1", "LOWMOM60 후보C", "REJECT(2026-09-04, 과거 HOLD)", "policy.json",
     "lowmom60-test-negative-regime-diagnosis-2026-09.md (REJECT, 최신) / "
     "lowmom60-candidate-c-engine-verification-2026-08.md (HOLD, 구)"),
    ("sector_neutral_pbr_growth_v1", "업종중립 PBR+성장 decile", "HOLD", "policy.json",
     "sector-neutral-engine-verification-2026-09.md"),
    ("sector_neutral_pbr_growth_v1_top30", "업종중립 PBR+성장 top30", "HOLD", "policy.json",
     "sector-neutral-engine-verification-2026-09.md"),
    ("factor_earnings_yield_v1", "Earnings Yield (mp=30)", "HOLD", "policy_30.json",
     "factor-earnings-yield-mtm-reverification-2026-08.md (HOLD, mp=30 정본)"),
    ("ew_benchmark_liquid_v1", "적격 유니버스 EW", "BENCHMARK", "policy.json",
     "build_selection_ew_benchmark.py (진단 전용 벤치마크)"),
]


# ---------------------------------------------------------------- phase 1


def build_curves():
    os.makedirs(OUT_DIR, exist_ok=True)
    out = json.load(open(CURVES_PATH, encoding="utf-8")) if os.path.exists(CURVES_PATH) else {}
    resolved_cache = {}
    for sid, label, status, policy_file, source in CANDIDATES:
        key = sid + "::" + policy_file
        if key in out:
            print("  skip (이미 있음): " + key, flush=True)
            continue
        t0 = time.time()
        if sid not in resolved_cache:
            resolved_cache[sid] = run_smoke(sid, START, END, REPO_ROOT)
        base = resolved_cache[sid]
        params = json.load(open(os.path.join(LAB, "strategies", sid, policy_file), encoding="utf-8"))
        cfg = PortfolioConfig(
            initial_capital=params["portfolio"]["initialCapital"],
            max_positions=params["portfolio"]["maxPositions"],
            equal_weight=params["portfolio"]["equalWeight"],
            fractional_shares=params["portfolio"]["fractionalShares"],
            tie_break=params["portfolio"]["tieBreak"])
        portfolio, snaps = schedule_with_monthly_mtm(
            base["resolved"], cfg, base["bars_by_ticker"], base["calendar"], START, END)
        out[key] = {
            "strategyId": sid, "label": label, "status": status, "policyFile": policy_file,
            "sourceFinding": source, "period": START + " ~ " + END,
            "universeMode": base["diag"]["universeMode"], "runClass": base["diag"]["runClass"],
            "cost": params["cost"], "maxPositions": params["portfolio"]["maxPositions"],
            "accounting": "monthly mark-to-market (pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm)",
            "closedPositions": len(portfolio.closed_positions),
            "openAtEnd": len(portfolio.open_positions),
            "snapshots": [[d, float(e)] for d, e in snaps],
            "elapsedSeconds": round(time.time() - t0, 1),
        }
        print("  %s: %d개월 · 청산 %d (%.0fs)" % (
            label, len(snaps), len(portfolio.closed_positions), time.time() - t0), flush=True)
        with open(CURVES_PATH, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved:", CURVES_PATH)


# -------------------------------------------------- phase 1b: EW 벤치마크 편향 측정
#
# `ew_benchmark_liquid_v1` 은 maxPositions=1500 인데 월평균 적격종목은 1,029개다.
# 엔진 사이징이 `cash / maxPositions` 고정이라 (1) 차액만큼 현금이 놀고
# (2) 슬롯예산이 1억/1500 = 66,667원이라 **주가가 66,667원을 넘는 종목은
# fractionalShares=False 에서 1주도 못 산다**. 둘 다 EW 벤치마크를 아래로
# 끌어내리고, 그만큼 "EW 대비 alpha" 를 위로 부풀린다. 이 저장소의 모든
# 기존 findings 가 이 벤치마크를 썼으므로 정본으로 계속 쓰되, 얼마나
# 부풀려졌는지 재기 위해 **현금·주가하한 제약이 없는 오프라인 EW** 를
# 같은 종목 리스트·같은 월말 격자·같은 30bp 로 따로 만든다.


def build_ew_offline():
    sid = "ew_benchmark_liquid_v1"
    base = run_smoke(sid, START, END, REPO_ROOT)
    sel = json.load(open(os.path.join(LAB, "strategies", sid, "selection.json"), encoding="utf-8"))
    curves = json.load(open(CURVES_PATH, encoding="utf-8"))
    dates = [d for d, _ in curves[sid + "::policy.json"]["snapshots"]]

    # {리밸런싱일: set(ticker)} 로 뒤집는다. selection 은 {ticker: [{date, ...}]}.
    by_date = {}
    for tk, evs in sel["selection"].items():
        for ev in evs:
            d = ev if isinstance(ev, str) else (ev.get("date") or ev.get("signalDate"))
            by_date.setdefault(d, set()).add(tk)
    rebal_dates = sorted(by_date)

    closes = {}
    for tk, bars in base["bars_by_ticker"].items():
        if not bars.empty:
            closes[tk] = dict(zip(bars.index.astype(str), bars["close"].astype(float).values))

    def close_at(tk, d):
        """d 이하 최신 종가. 거래정지·상장폐지 구간은 None(0 으로 안 채운다)."""
        s = closes.get(tk)
        if not s:
            return None
        if d in s:
            return s[d]
        ks = [k for k in s if k <= d]
        return s[max(ks)] if ks else None

    def held_at(d):
        prior = [r for r in rebal_dates if r <= d]
        return by_date[prior[-1]] if prior else set()

    # 두 변형을 같은 데이터로 함께 만든다 - 엔진 EW 와의 격차를 두 원인으로 가르기
    # 위해서다. "reset" 은 매 리밸런싱일에 동일가중으로 되돌리고(월별 재설정
    # 보너스 포함), "drift" 는 엔진과 같이 되돌리지 않고 비중이 표류하게 둔다
    # (continuousHoldOnRenewal). drift 와 엔진의 차이가 곧 현금·주가하한 제약분,
    # reset 과 drift 의 차이가 곧 재설정 보너스다.
    eq_reset, eq_drift = 1.0, 1.0
    c_reset, c_drift = [[dates[0], 1.0]], [[dates[0], 1.0]]
    w = {}                       # drift 변형의 종목별 보유 금액
    prev_held = set()
    for i in range(1, len(dates)):
        d0, d1 = dates[i - 1], dates[i]
        held = held_at(d0)
        rets = {}
        for tk in held:
            c0, c1 = close_at(tk, d0), close_at(tk, d1)
            if c0 and c1:
                rets[tk] = c1 / c0 - 1.0
        if not rets:
            c_reset.append([d1, eq_reset])
            c_drift.append([d1, eq_drift])
            continue
        cost = (len(held - prev_held) / float(len(held))) * (ENTRY_BPS + EXIT_BPS) / 1e4

        eq_reset *= (1 + float(np.mean(list(rets.values())))) * (1 - cost)

        # drift: 새로 들어온 종목만 그 시점 평균 보유금액으로 편입하고, 빠진
        # 종목은 뺀다. 남은 종목의 비중은 건드리지 않는다.
        w = {tk: v for tk, v in w.items() if tk in held}
        if w:
            avg = sum(w.values()) / len(w)
        else:
            avg = eq_drift / max(len(held), 1)
        for tk in held:
            w.setdefault(tk, avg)
        tot = sum(w.values())
        if tot > 0:
            scale = eq_drift / tot                    # 전체 자산에 맞춰 정규화
            w = {tk: v * scale for tk, v in w.items()}
        w = {tk: v * (1 + rets.get(tk, 0.0)) for tk, v in w.items()}
        eq_drift = sum(w.values()) * (1 - cost)

        prev_held = held
        c_reset.append([d1, eq_reset])
        c_drift.append([d1, eq_drift])
    return c_reset, c_drift, {"avgHeld": round(float(np.mean([len(held_at(d)) for d in dates])), 1),
                              "rebalanceDates": len(rebal_dates)}


def ewcheck():
    c_reset, c_drift, diag = build_ew_offline()
    cap = 100_000_000.0
    c_reset = [[d, e * cap] for d, e in c_reset]
    c_drift = [[d, e * cap] for d, e in c_drift]
    out = {"note": "현금·주가하한 제약이 없는 오프라인 EW 두 변형. reset=매 리밸런싱일 "
                   "동일가중 재설정, drift=엔진과 같이 비중 표류(continuousHoldOnRenewal). "
                   "engine EW ↔ drift 차이 = 현금·주가하한 제약분, drift ↔ reset 차이 = "
                   "월별 재설정 보너스. 비용은 양쪽 다 신규편입 비중 × 30bp.",
           "diag": diag,
           "reset": {"metrics": curve_metrics(c_reset), "annualReturns": annual_returns_mtm(c_reset)},
           "drift": {"metrics": curve_metrics(c_drift), "annualReturns": annual_returns_mtm(c_drift)},
           # analyze() 가 읽는 정본 곡선은 drift - 엔진과 같은 가중 규약이라
           # "같은 규약에서 현금제약만 없앤 EW" 가 되어 비교가 공정하다.
           "curve": c_drift, "curveReset": c_reset}
    path = os.path.join(OUT_DIR, "ew-offline.json")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "curve"},
                     ensure_ascii=False, indent=2, default=str))
    print("saved:", path)


# ---------------------------------------------------------------- phase 2


def load_index(path):
    """지수 일별 종가 -> ({date: level}, 정렬된 날짜). 두 파일의 날짜 컬럼명이 다르다."""
    d = pd.read_parquet(path)
    d = d.rename(columns={"usableFromDate": "date"})[["date", "value"]].dropna()
    d["date"] = d["date"].astype(str)
    return dict(zip(d["date"], d["value"].astype(float))), sorted(d["date"])


def index_curve(levels, dates_sorted, snap_dates, initial_capital):
    """전략 스냅샷 날짜에 맞춘 지수 바이앤홀드 곡선. 각 날짜에 대해 '그 날 이하
    최신 종가'를 쓴다(휴장·발표지연 대비). 비용은 바이앤홀드 1회 왕복 -
    진입 15bp 를 전 구간에, 청산 15bp 를 마지막 점에만 적용한다."""
    out = []
    for d in snap_dates:
        pos = np.searchsorted(dates_sorted, d, side="right") - 1
        out.append(None if pos < 0 else levels[dates_sorted[pos]])
    if any(v is None for v in out):
        return None
    base = out[0]
    curve = [initial_capital * (1 - ENTRY_BPS / 1e4) * v / base for v in out]
    curve[0] = float(initial_capital)                 # t0 는 비용 전 원금
    curve[-1] = curve[-1] * (1 - EXIT_BPS / 1e4)
    return [[d, float(e)] for d, e in zip(snap_dates, curve)]


def trim_to_active(snapshots):
    """진입 전 현금 구간을 잘라낸다. 시작이 늦은 전략(업종중립 2016-09 등)의
    평평한 현금 몇 달이 CAGR·변동성을 왜곡하는 것을 막는다. 마지막 평평한
    점을 남겨서 첫 수익률이 실제 그 달 수익률이 되게 한다."""
    cap = snapshots[0][1]
    for i in range(1, len(snapshots)):
        if snapshots[i][1] != cap:
            return snapshots[i - 1:]
    return snapshots


def monthly_returns(curve):
    return [curve[i][1] / curve[i - 1][1] - 1 for i in range(1, len(curve))]


def rolling_excess(curve_s, curve_b, window):
    """w개월 창의 연율화 초과수익 목록. 창이 모자라면 None."""
    if len(curve_s) - 1 < window:
        return None
    out = []
    for i in range(len(curve_s) - window):
        rs = (curve_s[i + window][1] / curve_s[i][1]) ** (12.0 / window) - 1
        rb = (curve_b[i + window][1] / curve_b[i][1]) ** (12.0 / window) - 1
        out.append(rs - rb)
    return out


def t_stat(xs):
    a = np.array(xs, dtype=float)
    if len(a) < 3 or a.std(ddof=1) == 0:
        return None
    return float(a.mean() / (a.std(ddof=1) / np.sqrt(len(a))))


def _roll_summary(x):
    if x is None:
        return None
    return {"n": len(x), "mean": round(float(np.mean(x)), 4),
            "median": round(float(np.median(x)), 4),
            "min": round(float(np.min(x)), 4), "max": round(float(np.max(x)), 4),
            "positiveShare": round(sum(v > 0 for v in x) / float(len(x)), 3)}


def compare(curve_s, curve_b, partial_years):
    """전략 곡선 vs 벤치마크 곡선. 두 곡선은 같은 날짜 배열이어야 한다."""
    assert [d for d, _ in curve_s] == [d for d, _ in curve_b]
    ms, mb = monthly_returns(curve_s), monthly_returns(curve_b)
    ex = [a - b for a, b in zip(ms, mb)]
    ann_s, ann_b = annual_returns_mtm(curve_s), annual_returns_mtm(curve_b)
    years = sorted(ann_s)
    full = [y for y in years if y not in partial_years]
    ex_ann = dict((y, round(ann_s[y] - ann_b[y], 4)) for y in years)
    wins = [y for y in years if ex_ann[y] > 0]
    m_s, m_b = curve_metrics(curve_s), curve_metrics(curve_b)
    tv = t_stat(ex)
    return {
        "strategy": m_s, "benchmark": m_b,
        "cagrExcess": round(m_s["cagr"] - m_b["cagr"], 4),
        "annualStrategy": ann_s, "annualBenchmark": ann_b, "annualExcess": ex_ann,
        "avgAnnualStrategy": round(float(np.mean([ann_s[y] for y in years])), 4),
        "avgAnnualBenchmark": round(float(np.mean([ann_b[y] for y in years])), 4),
        "avgAnnualExcess": round(float(np.mean([ex_ann[y] for y in years])), 4),
        "avgAnnualExcess_fullYearsOnly": (
            round(float(np.mean([ex_ann[y] for y in full])), 4) if full else None),
        "winYears": len(wins), "totalYears": len(years),
        "winYearShare": round(len(wins) / float(len(years)), 3),
        "winYearsList": wins,
        "topYearContribution": _top_year_contribution(ex_ann),
        "rolling3Y": _roll_summary(rolling_excess(curve_s, curve_b, 36)),
        "rolling5Y": _roll_summary(rolling_excess(curve_s, curve_b, 60)),
        "excessMonthlyMean": round(float(np.mean(ex)), 5),
        "excessTStat": (round(tv, 3) if tv is not None else None),
        "nMonths": len(ms),
    }


def _top_year_contribution(ex_ann):
    """단일 연도 의존도. 합이 양수일 때만 의미가 있으므로 그 외에는 None."""
    tot = sum(ex_ann.values())
    if tot <= 0:
        return None
    best = max(ex_ann, key=lambda y: ex_ann[y])
    return {"year": best, "excess": ex_ann[best], "shareOfTotalExcess": round(ex_ann[best] / tot, 3)}


def analyze():
    curves = json.load(open(CURVES_PATH, encoding="utf-8"))
    kospi_lv, kospi_d = load_index(KOSPI_PATH)
    kosdaq_lv, kosdaq_d = load_index(KOSDAQ_PATH)
    ew_by_date = dict((d, e) for d, e in curves["ew_benchmark_liquid_v1::policy.json"]["snapshots"])
    ew_off_path = os.path.join(OUT_DIR, "ew-offline.json")
    ew_off_by_date = (dict((d, e) for d, e in json.load(open(ew_off_path, encoding="utf-8"))["curve"])
                      if os.path.exists(ew_off_path) else {})
    # 상태·라벨은 curves.json 에 구워진 값이 아니라 CANDIDATES 를 정본으로 읽는다 -
    # findings 의 verdict 가 바뀌면 곡선을 다시 돌리지 않고 여기만 고치면 된다.
    meta = dict((sid + "::" + pf, (label, status, source))
                for sid, label, status, pf, source in CANDIDATES)

    results = {}
    for key, rec in curves.items():
        rec["label"], rec["status"], rec["sourceFinding"] = meta[key]
        if rec["status"] == "BENCHMARK":
            continue
        for window_name, cut in (("full", None), ("throughLastFullYear", LAST_FULL_YEAR_END)):
            snaps = trim_to_active(rec["snapshots"])
            if cut:
                snaps = [s for s in snaps if s[0] <= cut]
            if len(snaps) < 24:
                continue
            dates = [d for d, _ in snaps]
            cap = snaps[0][1]
            def rebased(src):
                if not src or not all(d in src for d in dates):
                    return None
                b0 = src[dates[0]]
                return [[d, src[d] / b0 * cap] for d in dates]

            benches = {
                "KOSPI": index_curve(kospi_lv, kospi_d, dates, cap),
                "KOSDAQ": index_curve(kosdaq_lv, kosdaq_d, dates, cap),
                "UNIVERSE_EW": rebased(ew_by_date),
                "UNIVERSE_EW_OFFLINE": rebased(ew_off_by_date),
            }
            partial = set([2026]) if cut is None else set()
            results.setdefault(key, {})[window_name] = {
                "label": rec["label"], "status": rec["status"], "strategyId": rec["strategyId"],
                "policyFile": rec["policyFile"], "sourceFinding": rec["sourceFinding"],
                "maxPositions": rec["maxPositions"], "cost": rec["cost"],
                "universeMode": rec["universeMode"], "accounting": rec["accounting"],
                "closedPositions": rec["closedPositions"], "openAtEnd": rec["openAtEnd"],
                "window": dates[0] + " ~ " + dates[-1], "nMonths": len(dates) - 1,
                "partialYears": sorted(partial),
                "self": curve_metrics(snaps),
                "vs": dict((name, (compare(snaps, c, partial) if c is not None else None))
                           for name, c in benches.items()),
            }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "enginePeriod": START + " ~ " + END,
                   "accounting": "monthly mark-to-market only (실현손익 누적 미사용)",
                   "costNote": "전략: policy.json 왕복 30bp·슬리피지 0. "
                               "지수: 바이앤홀드 1회 왕복 30bp.",
                   "indexNote": "KOSPI·KOSDAQ 은 배당 미포함 가격지수. 전략도 배당 미포함이라 "
                                "같은 기준이지만, 배당을 넣으면 지수 쪽이 더 유리해진다.",
                   "results": results}, f, ensure_ascii=False, indent=1)
    print("saved:", RESULT_PATH)
    print_table(results)


def pct(x):
    return "" if x is None else ("%.2f%%" % (x * 100))


def print_table(results):
    for window in ("full", "throughLastFullYear"):
        print("\n===== " + window + " =====")
        print("전략 vs 벤치 | 상태 | 기간 | CAGR | 시장CAGR | CAGR초과 | 평균연수익 | 평균초과 | "
              "초과연도비율 | Roll3Y | Roll5Y | MDD | Sharpe | ExcessT | N")
        for key, byw in results.items():
            e = byw.get(window)
            if not e:
                continue
            for bname in ("KOSPI", "KOSDAQ", "UNIVERSE_EW", "UNIVERSE_EW_OFFLINE"):
                v = e["vs"].get(bname)
                if v is None:
                    print(e["label"] + " vs " + bname + " | 계산 불가")
                    continue
                r3, r5 = v["rolling3Y"], v["rolling5Y"]
                print(" | ".join([
                    e["label"] + " vs " + bname, e["status"], e["window"],
                    pct(v["strategy"]["cagr"]), pct(v["benchmark"]["cagr"]), pct(v["cagrExcess"]),
                    pct(v["avgAnnualStrategy"]), pct(v["avgAnnualExcess"]),
                    "%d/%d(%.0f%%)" % (v["winYears"], v["totalYears"], v["winYearShare"] * 100),
                    (pct(r3["median"]) + " pos%.0f%%" % (r3["positiveShare"] * 100)) if r3 else "",
                    (pct(r5["median"]) + " pos%.0f%%" % (r5["positiveShare"] * 100)) if r5 else "",
                    pct(v["strategy"]["mdd"]),
                    ("" if v["strategy"]["sharpe"] is None else "%.3f" % v["strategy"]["sharpe"]),
                    ("" if v["excessTStat"] is None else "%.2f" % v["excessTStat"]),
                    "%dm" % v["nMonths"],
                ]))


# ---------------------------------------------------------------- selftest


def selftest():
    # trim_to_active: 앞의 평평한 현금 구간은 마지막 하나만 남긴다.
    s = [["2016-01-01", 100.0], ["2016-01-29", 100.0], ["2016-02-29", 110.0]]
    assert trim_to_active(s) == s[1:], trim_to_active(s)
    assert trim_to_active([["a", 100.0], ["b", 100.0]]) == [["a", 100.0], ["b", 100.0]]

    # index_curve: 진입 15bp + 청산 15bp 가 각각 한 번씩만 물린다.
    lv = {"2020-01-31": 100.0, "2020-02-29": 200.0}
    d = ["2020-01-31", "2020-02-29"]
    c = index_curve(lv, d, d, 1000.0)
    assert c[0][1] == 1000.0
    assert abs(c[1][1] - 1000.0 * 0.9985 * 2 * 0.9985) < 1e-9, c

    # compare: 전략과 벤치가 같으면 초과는 정확히 0, 승리 연도 0.
    cs = [["2020-01-31", 100.0], ["2020-12-31", 120.0], ["2021-12-31", 132.0]]
    r = compare(cs, [list(x) for x in cs], set())
    assert r["cagrExcess"] == 0.0 and r["winYears"] == 0 and r["avgAnnualExcess"] == 0.0, r
    assert r["topYearContribution"] is None      # 총초과 0 이면 의존도는 정의되지 않는다

    # rolling_excess: 창이 데이터보다 길면 None(0 으로 채우지 않는다).
    assert rolling_excess(cs, cs, 36) is None

    # 단일 연도 의존도: 한 해가 전부면 share = 1.0
    assert _top_year_contribution({2020: 0.10, 2021: 0.0})["shareOfTotalExcess"] == 1.0
    print("selftest ok (8 assertions)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--curves", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--ewcheck", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.curves:
        build_curves()
    elif a.ewcheck:
        ewcheck()
    elif a.analyze:
        analyze()
    else:
        ap.error("--curves / --ewcheck / --analyze / --selftest 중 하나")


if __name__ == "__main__":
    main()
