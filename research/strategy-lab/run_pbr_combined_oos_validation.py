#!/usr/bin/env python
"""dropout×maxexcl 파라미터 스윕(findings/pbr-combined-paramsweep-2026-08.md)이
"nDrop=2+pct=0.8이 격자 전체 최선"이라 찾은 것은 **전체 기간(2016~2026)을
다 보고 사후에 고른 값**이다 - 그 findings 자신이 "OOS 미검증이라 look-ahead
위험이 있다"고 한계로 적어 뒀다. `run_strategy_validation.py`가 CAND1·
Opening Fade에 쓴 원칙("TRAIN에서만 스윕, 선택은 고정한 뒤 VALID·TEST는
보고만 한다")을 그대로 이 12격자(3 dropout-alone + 9 combined)에 적용해
같은 결론이 OOS에서도 유지되는지 확인한다.

방법: run_pbr_combined_paramsweep.py와 같은 인메모리 격자 계산(bars·
valuation·max5 한 번만 로드, run_smoke(rule_module=...))을 재사용하되,
curve_metrics()를 전체 기간이 아니라 월별 스냅샷을 시간순 60/15/25%로
자른 TRAIN/VALID/TEST 구간에 각각 적용한다(포지션이 구간 경계를 넘어
연속보유되는 건 그대로 두고, 그 구간 자체의 시작 시점 자본 대비 등락만
그 구간의 metric으로 본다 - CAND1/Opening Fade의 세션 단위 분할과 같은
원리를 월별 시가평가 곡선에 적용한 것).

  python run_pbr_combined_oos_validation.py
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
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm, curve_metrics  # noqa: E402

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
N_DROP_GRID = [2, 3, 5]
PERCENTILE_GRID = [0.7, 0.8, 0.9]
SPLIT_FRACTIONS = {"TRAIN": 0.60, "VALID": 0.15, "TEST": 0.25}
SELECTION_METRIC = "sharpe"  # TRAIN에서 격자를 고를 기준


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


def split_snapshots(snapshots, fractions=SPLIT_FRACTIONS):
    """스냅샷(월별 (date,equity)) 리스트를 시간순 60/15/25%로 자른다. 각
    구간은 t0=그 구간 첫 스냅샷 자기 자신 - CAND1/Opening Fade의 세션분할과
    같은 원리(그 구간 자체의 등락만 본다, 전체기간 첫 자본 대비가 아님)."""
    n = len(snapshots)
    n_train = int(round(n * fractions["TRAIN"]))
    n_valid = int(round(n * fractions["VALID"]))
    return {
        "TRAIN": snapshots[:n_train + 1],  # +1: 그 구간 시작점(t0) 포함
        "VALID": snapshots[n_train:n_train + n_valid + 1],
        "TEST": snapshots[n_train + n_valid:],
    }


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
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-combined-oos")
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

    def flatten(selection_by_month):
        out = {}
        for asOf, holdings in selection_by_month.items():
            for t, hold_sessions in holdings.items():
                out.setdefault(t, []).append({"date": asOf, "holdSessions": hold_sessions})
        return out

    def build_dropout_selection(n_drop):
        selection_by_month = {}
        held = []
        for asOf in rebalance_dates:
            if asOf not in hold_sessions_by_date or asOf not in eligible_by_month:
                continue
            ranked = eligible_by_month[asOf]
            new_selection = next_selection(held, ranked, TOP_N, n_drop)
            selection_by_month[asOf] = {t: hold_sessions_by_date[asOf] for t in new_selection}
            held = new_selection
        return selection_by_month

    threshold_by_month_per_pct = {
        pct: eligible.dropna(subset=["max5"]).groupby("asOf")["max5"].quantile(pct)
        for pct in PERCENTILE_GRID
    }

    def apply_maxexcl(selection_by_month, percentile):
        thresh_by_month = threshold_by_month_per_pct[percentile]
        out = {}
        for asOf, holdings in selection_by_month.items():
            threshold = thresh_by_month.get(asOf)
            for t, hold_sessions in holdings.items():
                m5 = max5_lookup.get((t, asOf))
                if threshold is not None and m5 is not None and m5 >= threshold:
                    continue
                out.setdefault(t, []).append({"date": asOf, "holdSessions": hold_sessions})
        return out

    def measure(selection_by_ticker):
        rule = make_rule_module(params, selection_by_ticker)
        base = run_smoke("pbr_value_v1_combined_oos", START, END, REPO_ROOT, rule_module=rule)
        resolved = base["resolved"]
        portfolio_cfg = PortfolioConfig(
            initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
            equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
            tie_break=params["portfolio"]["tieBreak"])
        portfolio, snapshots = schedule_with_monthly_mtm(
            resolved, portfolio_cfg, base["bars_by_ticker"], base["calendar"], START, END)
        by_split = split_snapshots(snapshots)
        return {name: curve_metrics(snaps) for name, snaps in by_split.items()}

    grid_results = {}
    dropout_selection_cache = {}
    for n_drop in N_DROP_GRID:
        dropout_selection_cache[n_drop] = build_dropout_selection(n_drop)
        key = f"nDrop={n_drop}_maxexcl=none"
        grid_results[key] = measure(flatten(dropout_selection_cache[n_drop]))
        print(f"  {key}: TRAIN sharpe={grid_results[key]['TRAIN']['sharpe']} "
              f"VALID sharpe={grid_results[key]['VALID']['sharpe']} "
              f"TEST sharpe={grid_results[key]['TEST']['sharpe']} ({time.time()-t0:.0f}s)")
        for pct in PERCENTILE_GRID:
            combined = apply_maxexcl(dropout_selection_cache[n_drop], pct)
            key2 = f"nDrop={n_drop}_maxexcl={pct}"
            grid_results[key2] = measure(combined)
            print(f"  {key2}: TRAIN sharpe={grid_results[key2]['TRAIN']['sharpe']} "
                  f"VALID sharpe={grid_results[key2]['VALID']['sharpe']} "
                  f"TEST sharpe={grid_results[key2]['TEST']['sharpe']} ({time.time()-t0:.0f}s)")

    train_ranked = sorted(grid_results.items(),
                           key=lambda kv: (kv[1]["TRAIN"][SELECTION_METRIC] is None,
                                           kv[1]["TRAIN"][SELECTION_METRIC] or -999),
                           reverse=True)
    train_best_key = train_ranked[0][0]
    full_sample_best_key = "nDrop=2_maxexcl=0.8"  # findings/pbr-combined-paramsweep-2026-08.md

    print(f"\nTRAIN에서 고른 최선: {train_best_key} (기준={SELECTION_METRIC})")
    print(f"전체기간 스윕이 골랐던 것: {full_sample_best_key}")

    summary = {k: grid_results[k] for k in {train_best_key, full_sample_best_key, "nDrop=3_maxexcl=none"}}
    print("\n", json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pbr-combined-oos-validation")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-combined-oos-validation.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "dropout x maxexcl 파라미터 스윕의 '최선' 선택이 OOS에서 "
                       "유지되는지 확인 - TRAIN에서만 격자를 고르고 VALID·TEST는 "
                       "고정된 그 선택을 보고만 한다(CAND1·Opening Fade와 같은 원칙). "
                       "findings/pbr-combined-paramsweep-2026-08.md 후속.",
            "selectionMetric": SELECTION_METRIC, "splitFractions": SPLIT_FRACTIONS,
            "trainBestKey": train_best_key, "fullSampleBestKey": full_sample_best_key,
            "period": f"{START} ~ {END}", "allGridResults": grid_results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
