#!/usr/bin/env python
"""dropout+maxexcl 결합(nDrop=2/pct=0.8, OOS 검증 통과 - findings/
pbr-combined-oos-validation-2026-08.md)이 baseline PBR과 같은 문제를
갖는지 확인 - baseline은 EW 대비 초과 로그수익의 **98.6%가 2022년
단 한 해**에서 나왔다(2026-08-22 확인, CLAUDE.md). combined도 같은
쏠림이면 "OOS에서 반전 없음"이 사실은 "2022년 하나만 잘 맞고 나머지는
다 소음"이라는 뜻일 수 있다 - 이 확인 없이는 combined을 production
후보로 올릴 근거가 안 된다.

방법: pbr_2022_decomposition.py가 못 찾아 새로 짠 것 - EW벤치마크
(ew_benchmark_liquid_v1)와 combined(nDrop=2/pct=0.8, in-memory로
재구성 - run_pbr_combined_paramsweep.py와 동일 로직) 둘 다 월별
시가평가 곡선을 만들고, 연도별 **로그수익률**(exp 아님, ln(equity_
연말/equity_전년말))을 구해 combined-EW 초과 로그수익의 연도별 비중을
계산한다.

  python pbr_combined_2022_concentration_check.py
"""
import json
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
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm  # noqa: E402

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
N_DROP = 2          # OOS 검증이 고른 값
MAXEXCL_PCT = 0.8   # OOS 검증이 고른 값


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


def annual_log_returns(snapshots):
    """연도말(또는 구간 끝) 스냅샷 기준 ln(eq_y/eq_{y-1})."""
    by_year_last = {}
    for d, e in snapshots:
        by_year_last[int(d[:4])] = e
    years = sorted(by_year_last)
    prev = snapshots[0][1]
    out = {}
    for y in years:
        out[y] = float(np.log(by_year_last[y] / prev))
        prev = by_year_last[y]
    return out


def build_combined_selection(rebalance_dates, eligible_by_month, max5_lookup,
                              threshold_by_month, hold_sessions_by_date):
    held = []
    selection_by_month = {}
    for asOf in rebalance_dates:
        if asOf not in hold_sessions_by_date or asOf not in eligible_by_month:
            continue
        ranked = eligible_by_month[asOf]
        new_selection = next_selection(held, ranked, TOP_N, N_DROP)
        selection_by_month[asOf] = {t: hold_sessions_by_date[asOf] for t in new_selection}
        held = new_selection
    threshold = threshold_by_month
    out = {}
    for asOf, holdings in selection_by_month.items():
        thr = threshold.get(asOf)
        for t, hold_sessions in holdings.items():
            m5 = max5_lookup.get((t, asOf))
            if thr is not None and m5 is not None and m5 >= thr:
                continue
            out.setdefault(t, []).append({"date": asOf, "holdSessions": hold_sessions})
    return out


def run_curve(strategy_id, rule_module=None):
    base = run_smoke(strategy_id, START, END, REPO_ROOT, rule_module=rule_module)
    params = rule_module.PARAMS if rule_module is not None else base["params"]
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"])
    _, snapshots = schedule_with_monthly_mtm(
        base["resolved"], portfolio_cfg, base["bars_by_ticker"], base["calendar"], START, END)
    return snapshots


def main():
    t0 = time.time()
    with open(COMBINED_POLICY, encoding="utf-8") as f:
        params = json.load(f)

    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = sorted(val["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-combined-2022-concentration")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

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
    print(f"turnover rows={len(turnover_df)}, max5 rows={len(max5_df)} ({time.time()-t0:.0f}s)")

    merged = val.merge(turnover_df, on=["ticker", "asOf"], how="inner")
    eligible = merged[merged["turnover20"] >= MIN_TURNOVER].merge(
        max5_df, on=["ticker", "asOf"], how="left")
    eligible_by_month = {asOf: g.sort_values("pbr", ascending=True)["ticker"].tolist()
                          for asOf, g in eligible.groupby("asOf")}
    max5_lookup = {(r["ticker"], r["asOf"]): r["max5"] for _, r in max5_df.iterrows()}
    threshold_by_month = eligible.dropna(subset=["max5"]).groupby("asOf")["max5"].quantile(MAXEXCL_PCT)

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

    combined_selection = build_combined_selection(
        rebalance_dates, eligible_by_month, max5_lookup, threshold_by_month, hold_sessions_by_date)
    rule = make_rule_module(params, combined_selection)

    combined_snapshots = run_curve("pbr_value_v1_combined_2022check", rule_module=rule)
    ew_snapshots = run_curve("ew_benchmark_liquid_v1")
    print(f"combined months={len(combined_snapshots)}, ew months={len(ew_snapshots)} ({time.time()-t0:.0f}s)")

    combined_log = annual_log_returns(combined_snapshots)
    ew_log = annual_log_returns(ew_snapshots)
    years = sorted(set(combined_log) & set(ew_log))
    excess_by_year = {y: combined_log[y] - ew_log[y] for y in years}
    total_excess = sum(excess_by_year.values())
    share_by_year = {y: (round(v / total_excess, 4) if total_excess else None) for y, v in excess_by_year.items()}

    print("\nyear  combinedLogRet  ewLogRet  excessLogRet  shareOfTotalExcess")
    for y in years:
        print(f"{y}  {combined_log[y]:.4f}  {ew_log[y]:.4f}  {excess_by_year[y]:.4f}  {share_by_year[y]}")
    print(f"\ntotal excess log return: {total_excess:.4f}")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pbr-combined-2022-concentration")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-combined-2022-concentration.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "combined(nDrop=2/pct=0.8, OOS 검증 통과)이 baseline PBR과 같은 "
                       "2022년 쏠림(로그초과수익 98.6%, 2026-08-22 확인)을 갖는지 확인. "
                       "findings/pbr-combined-oos-validation-2026-08.md 후속.",
            "nDrop": N_DROP, "maxexclPercentile": MAXEXCL_PCT,
            "combinedLogReturnByYear": combined_log, "ewLogReturnByYear": ew_log,
            "excessLogReturnByYear": excess_by_year, "shareOfTotalExcessByYear": share_by_year,
            "totalExcessLogReturn": total_excess,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
