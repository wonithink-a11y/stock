#!/usr/bin/env python
"""dropout(nDrop) x maxexcl(exclusion percentile) 파라미터 스윕 - 2026-08-26
결합 실험(findings/pbr-dropout-maxexcl-combined-2026-08.md)이 nDrop=3·
percentile=80%라는 단일 조합에서만 나온 초가산적 효과인지, 격자 전체에서
재현되는 패턴인지 확인. 세션인수인계-2026-08-26.md §5-4 후속.

bars·valuation·max5·turnover20을 한 번만 로드하고(build_selection_dropout.py·
build_selection_maxexcl.py가 각자 다시 로드하던 것을 이 스윕에서는 공유),
engine/runner.py의 run_smoke(rule_module=...)에 인메모리 규칙 객체를 넘겨
strategies/pbr_value_v1_combined/rule.py와 동일한 로직(policy.json 재사용,
selection만 매 격자점마다 다시 계산)을 디스크에 쓰지 않고 반복 실행한다.

nDrop in {2,3,5} x exclusionPercentile in {0.7,0.8,0.9} = 9격자,
(3,0.8)은 이미 검증된 조합이라 재확인용으로 포함.

  python run_pbr_combined_paramsweep.py
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
    """rule.py를 그대로 재현 - selection.json 파일을 안 거치고 딕셔너리를
    직접 클로저로 참조한다(run_smoke의 rule_module= 인자용)."""
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

    mod = types.SimpleNamespace(
        PARAMS=params, compute_features=compute_features,
        generate_signals=generate_signals, risk_spec_for=risk_spec_for)
    return mod


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
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-combined-paramsweep")
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
        """{asOf: {ticker: holdSessions}} -> {ticker: [{date, holdSessions}, ...]}"""
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

    # 월별 임계값은 "그 달 보유종목" 30개가 아니라 build_selection_maxexcl.py와
    # 동일하게 "그 달 적격 유니버스"(turnover20>=1억 & pbr>0, 월 800+ 종목)
    # 전체를 percentile 기준으로 삼는다 - held 30개만으로 재계산하면 이미
    # 저PBR로 걸러진 좁은 표본의 자체 분포가 되어 원래 정의("시장 전체 상위
    # 20%")와 달라진다. percentile마다 한 번만 계산해 nDrop 루프 전체가 공유.
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
        base = run_smoke("pbr_value_v1_combined_sweep", START, END, REPO_ROOT, rule_module=rule)
        resolved = base["resolved"]
        portfolio_cfg = PortfolioConfig(
            initial_capital=params["portfolio"]["initialCapital"], max_positions=params["portfolio"]["maxPositions"],
            equal_weight=params["portfolio"]["equalWeight"], fractional_shares=params["portfolio"]["fractionalShares"],
            tie_break=params["portfolio"]["tieBreak"])
        portfolio, snapshots = schedule_with_monthly_mtm(
            resolved, portfolio_cfg, base["bars_by_ticker"], base["calendar"], START, END)
        metrics = curve_metrics(snapshots)
        metrics["closedPositionCount"] = len(portfolio.closed_positions)
        return metrics

    results = {}
    dropout_selection_cache = {}
    for n_drop in N_DROP_GRID:
        dropout_selection_cache[n_drop] = build_dropout_selection(n_drop)
        m = measure(flatten(dropout_selection_cache[n_drop]))
        key = f"nDrop={n_drop}_maxexcl=none"
        results[key] = m
        print(f"  {key}: CAGR={m['cagr']:.4f} MDD={m['mdd']:.4f} Sharpe={m['sharpe']} "
              f"closed={m['closedPositionCount']} ({time.time()-t0:.0f}s)")
        for pct in PERCENTILE_GRID:
            combined = apply_maxexcl(dropout_selection_cache[n_drop], pct)
            m2 = measure(combined)
            key2 = f"nDrop={n_drop}_maxexcl={pct}"
            results[key2] = m2
            print(f"  {key2}: CAGR={m2['cagr']:.4f} MDD={m2['mdd']:.4f} Sharpe={m2['sharpe']} "
                  f"closed={m2['closedPositionCount']} ({time.time()-t0:.0f}s)")

    print("\n", json.dumps(results, ensure_ascii=False, indent=2, default=str))

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pbr-combined-paramsweep")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pbr-combined-paramsweep.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "dropout(nDrop) x maxexcl(exclusion percentile) 격자 스윕 - "
                       "(3, 0.8) 단일 조합에서 나온 초가산적 결합 효과가 격자 전체에서 "
                       "재현되는지 확인. 세션인수인계-2026-08-26.md §5-4 후속.",
            "nDropGrid": N_DROP_GRID, "percentileGrid": PERCENTILE_GRID,
            "period": f"{START} ~ {END}", "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
