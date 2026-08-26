#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PBR combined(dropout nDrop=2 + MAX제외 pct=0.8, OOS 검증 통과 - findings/
pbr-combined-oos-validation-2026-08.md) — 사용자 질문(2026-08-26, "2022년
약세장에 방어적이었다면 약세장 타이밍 신호로 써도 되지 않나")에 대한 답을
이 프로젝트의 표준 절차로 실제 검증한다.

**이미 한 번 같은 길에서 실패했다** - baseline PBR로 똑같은 아이디어(미국
10Y 상승기=PBR에 유리한 국면 → 진입 타이밍 필터로 구현)를 시도했을 때
오히려 나빠졌다(CAGR +4.72%→+2.26%, findings/pbr-ratefilter-backtest-
2026-08.md). 그 실패 이후 이 프로젝트가 표준화한 절차 - "구성은 그대로
두고 노출(exposure_frac)만 조절하는 순수 오버레이" + "같은 평균노출을
상수로 건 대조군"으로 **타이밍 자체의 가치와 단순 디레버리징 효과를
분리**한다(trendbreakout_5dc_exposure_overlay_vs_baseline_mtm.py와 완전히
같은 방법론, 축·정규화·TRAIL_DAYS 전부 build_pbr_sizing_selection.py에서
무변경 재사용). combined은 PBR과 같은 방향(hiking에 유리)이라고 가정 -
PBR·LOWMOM60이 이미 그 방향으로 확인됐고 combined은 같은 저PBR 랭킹
위에 있다(invert 없음, PBR 오버레이와 동일).

구성(어떤 종목을 들고 있나)은 nDrop=2/pct=0.8 combined baseline과 100%
동일하게 두고 exposure_frac만 곱한다 - selection.json은 새로 안 만들고
run_pbr_combined_paramsweep.py류와 동일하게 인메모리로 재구성.

  python pbr_combined_exposure_overlay_vs_baseline_mtm.py
"""
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import run_smoke, _drop_suspension_rows  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import annual_returns_mtm, curve_metrics, schedule_with_monthly_mtm  # noqa: E402
from build_pbr_sizing_selection import load_rate_axis, exposure_lookup  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "strategies", "pbr_value_v1_dropout"))
from build_selection_dropout import next_selection  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRATEGY_LAB_DIR = os.path.dirname(os.path.abspath(__file__))
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                                "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
COMBINED_POLICY = os.path.join(STRATEGY_LAB_DIR, "strategies", "pbr_value_v1_combined", "policy.json")
START, END = "2016-01-01", "2026-08-14"
MIN_TURNOVER = 100_000_000.0
MAX_WINDOW, MAX_TOP_N = 21, 5
TOP_N = 30
N_DROP = 2
MAXEXCL_PCT = 0.8


def max5(daily_returns_window):
    top5 = sorted(daily_returns_window, reverse=True)[:MAX_TOP_N]
    return sum(top5) / len(top5) if top5 else None


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def make_rule_module(params, selection_by_ticker):
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
        PARAMS=params, compute_features=compute_features,
        generate_signals=generate_signals, risk_spec_for=risk_spec_for)


def build_combined_baseline_snapshots():
    with open(COMBINED_POLICY, encoding="utf-8") as f:
        params = json.load(f)
    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = sorted(val["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-combined-exposure-overlay")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    turnover_rows, max5_rows = [], []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        close, vol = bars["close"], bars["volume"]
        idx = close.index.astype(str)
        daily_ret = close.pct_change()
        turnover20 = (close * vol).rolling(20).mean()
        rolling_max5 = daily_ret.rolling(MAX_WINDOW).apply(lambda w: max5(list(w)), raw=False)
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            i = pos.get(t)
            if i is None:
                continue
            tv, m5 = turnover20.iloc[i], rolling_max5.iloc[i]
            if pd.isna(tv):
                continue
            turnover_rows.append({"ticker": ticker, "asOf": t, "turnover20": float(tv)})
            if not pd.isna(m5):
                max5_rows.append({"ticker": ticker, "asOf": t, "max5": float(m5)})
    turnover_df = pd.DataFrame(turnover_rows)
    max5_df = pd.DataFrame(max5_rows)

    merged = val.merge(turnover_df, on=["ticker", "asOf"], how="inner")
    eligible = merged[merged["turnover20"] >= MIN_TURNOVER].merge(max5_df, on=["ticker", "asOf"], how="left")
    eligible_by_month = {asOf: g.sort_values("pbr", ascending=True)["ticker"].tolist()
                          for asOf, g in eligible.groupby("asOf")}
    max5_lookup = {(r["ticker"], r["asOf"]): r["max5"] for _, r in max5_df.iterrows()}
    threshold_by_month = eligible.dropna(subset=["max5"]).groupby("asOf")["max5"].quantile(MAXEXCL_PCT)

    hold_sessions_by_date = {}
    for k, t in enumerate(rebalance_dates[:-1]):
        entry_date = calendar.next_session(t)
        exit_target = calendar.next_session(rebalance_dates[k + 1])
        if entry_date is None or exit_target is None:
            continue
        hold_sessions_by_date[t] = len(calendar.sessions_between(entry_date, exit_target))
    if rebalance_dates:
        hold_sessions_by_date.setdefault(rebalance_dates[-1], 21)

    held, selection_by_month = [], {}
    for asOf in rebalance_dates:
        if asOf not in hold_sessions_by_date or asOf not in eligible_by_month:
            continue
        new_selection = next_selection(held, eligible_by_month[asOf], TOP_N, N_DROP)
        selection_by_month[asOf] = {t: hold_sessions_by_date[asOf] for t in new_selection}
        held = new_selection

    combined_selection = {}
    for asOf, holdings in selection_by_month.items():
        thr = threshold_by_month.get(asOf)
        for t, hold_sessions in holdings.items():
            m5 = max5_lookup.get((t, asOf))
            if thr is not None and m5 is not None and m5 >= thr:
                continue
            combined_selection.setdefault(t, []).append({"date": asOf, "holdSessions": hold_sessions})

    rule = make_rule_module(params, combined_selection)
    base = run_smoke("pbr_value_v1_combined_overlay", START, END, REPO_ROOT, rule_module=rule)
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    _, snapshots = schedule_with_monthly_mtm(
        base["resolved"], portfolio_cfg, base["bars_by_ticker"], base["calendar"], START, END)
    return snapshots


def build_overlay(snapshots, exposure_of):
    overlay = [snapshots[0]]
    exposures = []
    for i in range(1, len(snapshots)):
        date_prev, eq_prev_base = snapshots[i - 1]
        date_cur, eq_cur_base = snapshots[i]
        r = eq_cur_base / eq_prev_base - 1.0
        frac = exposure_of(date_prev)
        if frac is None:
            frac = 0.0
        eq_overlay_prev = overlay[-1][1]
        overlay.append((date_cur, eq_overlay_prev * (1 + frac * r)))
        exposures.append((date_cur, frac))
    return overlay, exposures


def build_constant_exposure(snapshots, constant_frac):
    overlay = [snapshots[0]]
    for i in range(1, len(snapshots)):
        _, eq_prev_base = snapshots[i - 1]
        date_cur, eq_cur_base = snapshots[i]
        r = eq_cur_base / eq_prev_base - 1.0
        eq_overlay_prev = overlay[-1][1]
        overlay.append((date_cur, eq_overlay_prev * (1 + constant_frac * r)))
    return overlay


def exposure_by_year(exposures):
    by_year = {}
    for d, f in exposures:
        by_year.setdefault(d[:4], []).append(f)
    return {y: round(sum(v) / len(v), 3) for y, v in sorted(by_year.items())}


def main():
    t0 = time.time()
    print("=== PBR combined(nDrop=2/pct=0.8) 미국10Y 노출 오버레이 vs baseline vs 상수노출 대조군 ===")
    snaps = build_combined_baseline_snapshots()
    base_metrics = curve_metrics(snaps)
    base_ann = annual_returns_mtm(snaps)
    print(f"  baseline: {len(snaps)} monthly snapshots ({time.time()-t0:.0f}s)")

    rate_df = load_rate_axis()
    exposure_of = exposure_lookup(rate_df)
    overlay_snaps, exposures = build_overlay(snaps, exposure_of)
    overlay_metrics = curve_metrics(overlay_snaps)
    overlay_ann = annual_returns_mtm(overlay_snaps)

    avg_exposure = round(sum(f for _, f in exposures) / len(exposures), 3)
    exp_by_year = exposure_by_year(exposures)

    const_snaps = build_constant_exposure(snaps, avg_exposure)
    const_metrics = curve_metrics(const_snaps)
    calmar_const = round(const_metrics["cagr"] / abs(const_metrics["mdd"]), 4) if const_metrics["mdd"] != 0 else None

    cagr_gap = round(overlay_metrics["cagr"] - base_metrics["cagr"], 4)
    sharpe_gap = (round(overlay_metrics["sharpe"] - base_metrics["sharpe"], 4)
                  if base_metrics["sharpe"] is not None and overlay_metrics["sharpe"] is not None else None)
    calmar_base = round(base_metrics["cagr"] / abs(base_metrics["mdd"]), 4) if base_metrics["mdd"] != 0 else None
    calmar_overlay = round(overlay_metrics["cagr"] / abs(overlay_metrics["mdd"]), 4) if overlay_metrics["mdd"] != 0 else None
    timing_value_cagr = round(overlay_metrics["cagr"] - const_metrics["cagr"], 4)
    timing_value_sharpe = (round(overlay_metrics["sharpe"] - const_metrics["sharpe"], 4)
                            if overlay_metrics["sharpe"] is not None and const_metrics["sharpe"] is not None else None)
    timing_value_mdd = round(overlay_metrics["mdd"] - const_metrics["mdd"], 4)

    print(f"\nbaseline(구성=노출100%): CAGR={base_metrics['cagr']:.4f} MDD={base_metrics['mdd']:.4f} "
          f"Sharpe={base_metrics['sharpe']} Calmar={calmar_base}")
    print(f"overlay(macro 노출조절): CAGR={overlay_metrics['cagr']:.4f} MDD={overlay_metrics['mdd']:.4f} "
          f"Sharpe={overlay_metrics['sharpe']} Calmar={calmar_overlay}")
    print(f"대조군(상수 {avg_exposure} 노출): CAGR={const_metrics['cagr']:.4f} MDD={const_metrics['mdd']:.4f} "
          f"Sharpe={const_metrics['sharpe']} Calmar={calmar_const}")
    print(f"\n** 순수 타이밍가치(overlay-대조군): CAGR={timing_value_cagr}, MDD={timing_value_mdd}, "
          f"Sharpe={timing_value_sharpe} **")
    print("연도별 평균노출:", exp_by_year)

    result = {
        "period": f"{START} ~ {END}", "nDrop": N_DROP, "maxexclPercentile": MAXEXCL_PCT,
        "baseline": {"resultTable": base_metrics, "calmar": calmar_base, "annualReturns": base_ann},
        "constantExposureControl": {"constantFrac": avg_exposure, "resultTable": const_metrics, "calmar": calmar_const},
        "timingValue_overlayMinusConstant": {"cagr": timing_value_cagr, "mdd": timing_value_mdd, "sharpe": timing_value_sharpe},
        "overlay": {"resultTable": overlay_metrics, "calmar": calmar_overlay, "annualReturns": overlay_ann,
                    "avgExposureFrac": avg_exposure, "exposureFracByYear": exp_by_year},
        "cagrGap_overlayMinusBaseline": cagr_gap, "sharpeGap_overlayMinusBaseline": sharpe_gap,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pbr-combined-exposure-overlay-vs-baseline-mtm")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-combined-exposure-overlay-vs-baseline-mtm.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "context": "PBR combined(nDrop=2/pct=0.8) 미국10Y 노출오버레이 - 사용자 질문"
                              "(2022년 약세장 방어 성격을 약세장 타이밍 신호로 쓸 수 있는가)에 대한 "
                              "답. baseline PBR로 이미 실패한 진입필터 대신 순수노출 오버레이+"
                              "상수노출 대조군으로 타이밍가치와 디레버리징효과를 분리.",
                   "result": result}, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
