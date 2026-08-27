#!/usr/bin/env python
"""DD252 Arm A - 구조적 alpha인지 국면노출인지 분해 (사용자 지시, 2026-08-27).

1. 2026(부분연도) 제외 성과
2. 연도별 DD252-BM1 초과수익(로그) 및 전체 초과분 대비 비중
3. 상승장/하락장/횡보장별 성과(KOSPI 12개월 추세 기준)
4. 초과성과의 종목 집중도(closed position PnL 상위 집중)
5. 2019·2023 초과성과 원인(업종 구성 - docs/data/sector-mapping.json)

DD252 gross(비용 0) 1회만 재실행(비용은 이 분해 목적과 무관 - 이미 net과의
차이가 작다는 건 확인됨), BM1도 함께 재실행해 월별 전체 스냅샷·전체
closed_position을 얻는다(이전 full_backtest 스크립트는 연도말 값만 남겨
이 분해에 필요한 정밀도가 부족).

production 변경 없음, 커밋 없음 - 결과만 보고.

  python analyze_dd252_arm_a_decomposition.py
"""
import json
import os
import sys
import time
import types
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from pbr_vs_ew_monthly_mtm import _month_end_dates, curve_metrics  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STRATEGY_LAB_DIR = os.path.dirname(os.path.abspath(__file__))
DD252_DIR = os.path.join(STRATEGY_LAB_DIR, "strategies", "dd252_v1_cohort")
SECTOR_MAP_PATH = os.path.join(REPO_ROOT, "docs", "data", "sector-mapping.json")
UNIVERSE_A1A = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
UNIVERSE_A1B = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1b", "delisted.jsonl")
KOSPI_PATH = os.path.join(STRATEGY_LAB_DIR, "data", "market-regime", "krkospi_raw.parquet")
START, END = "2016-01-01", "2026-08-14"
N_COHORTS = 6
TOTAL_CAPITAL = 100_000_000.0
COHORT_CAPITAL = TOTAL_CAPITAL / N_COHORTS
MAX_POSITIONS_PER_COHORT = 30
MIN_HISTORY = 273


def make_rule_module(params, selection_by_ticker):
    hold_col = "dd252HoldSessions"
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


def schedule_cohort(resolved, portfolio_cfg, bars_by_ticker, calendar, start, end):
    portfolio = Portfolio(portfolio_cfg)
    close_lookup = {}
    for ticker, bars in bars_by_ticker.items():
        if bars.empty:
            continue
        idx = bars.index.astype(str)
        close_lookup[ticker] = dict(zip(idx, bars["close"].values))

    by_entry_date, by_exit_date = {}, {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)

    month_ends = set(_month_end_dates(calendar, start, end))
    event_dates = sorted(set(by_entry_date) | set(by_exit_date) | month_ends)
    snapshots = [(start, portfolio_cfg.initial_capital)]

    for date in event_dates:
        exits_today, same_bar_exit_candidates = [], []
        exit_symbols_queued = set()
        for item in by_exit_date.get(date, []):
            sig, order, entry_fill, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions and order.symbol not in exit_symbols_queued:
                exit_symbols_queued.add(order.symbol)
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
            elif order.order_date == date:
                same_bar_exit_candidates.append((order.symbol, exit_fill))
        candidates_today = [(order, entry_fill) for (_, order, entry_fill, _, _, _) in by_entry_date.get(date, [])]
        portfolio.process_day(date, exits_today, candidates_today)

        if same_bar_exit_candidates:
            same_bar_exits_admitted = [
                (symbol, exit_fill, portfolio.open_positions[symbol]["shares"])
                for symbol, exit_fill in same_bar_exit_candidates
                if symbol in portfolio.open_positions
            ]
            if same_bar_exits_admitted:
                portfolio.process_day(date, same_bar_exits_admitted, [])

        if date in month_ends:
            closes_today = {}
            for sym in portfolio.open_positions:
                c = close_lookup.get(sym, {}).get(date)
                if c is not None:
                    closes_today[sym] = c
            snapshots.append((date, portfolio.equity(closes_today)))

    return portfolio, snapshots


def run_dd252_gross():
    with open(os.path.join(DD252_DIR, "policy.json"), encoding="utf-8") as f:
        params = json.load(f)
    params["cost"]["entryCostBps"] = 0.0
    params["cost"]["exitCostBps"] = 0.0
    with open(os.path.join(DD252_DIR, "selection.json"), encoding="utf-8") as f:
        sel_data = json.load(f)
    selection_by_ticker = sel_data["selection"]
    cohort_lookup = {}
    for ticker, entries in selection_by_ticker.items():
        for e in entries:
            cohort_lookup[(ticker, e["date"])] = e["cohort"]

    rule = make_rule_module(params, selection_by_ticker)
    base = run_smoke("dd252_arm_a_decomp", START, END, REPO_ROOT, rule_module=rule)
    resolved, bars_by_ticker, calendar = base["resolved"], base["bars_by_ticker"], base["calendar"]

    resolved_by_cohort = {c: [] for c in range(N_COHORTS)}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        c = cohort_lookup.get((order.symbol, order.signal_date))
        if c is not None:
            resolved_by_cohort[c].append(item)

    portfolio_cfg = PortfolioConfig(initial_capital=COHORT_CAPITAL, max_positions=MAX_POSITIONS_PER_COHORT,
                                     equal_weight=True, fractional_shares=False, tie_break="ticker_ascending")
    cohort_snapshots, all_closed = {}, []
    for c in range(N_COHORTS):
        portfolio, snapshots = schedule_cohort(resolved_by_cohort[c], portfolio_cfg, bars_by_ticker, calendar, START, END)
        cohort_snapshots[c] = snapshots
        all_closed.extend(portfolio.closed_positions)

    n_snap = min(len(cohort_snapshots[c]) for c in range(N_COHORTS))
    combined = [(cohort_snapshots[0][i][0], sum(cohort_snapshots[c][i][1] for c in range(N_COHORTS)))
                for i in range(n_snap)]
    return combined, all_closed, bars_by_ticker, calendar


def build_bm1(bars_by_ticker, calendar, min_history=MIN_HISTORY):
    def monthly_rebalance_dates(calendar, start, end):
        days = calendar.sessions_between(start, end)
        out, seen = [], set()
        for d in days:
            ym = d[:7]
            if ym not in seen:
                seen.add(ym)
                out.append(d)
        return out

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    monthly_returns = {}
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < min_history:
            continue
        close, open_ = bars["close"], bars["open"]
        idx = close.index.astype(str)
        lag = close.shift(21)
        hi = lag.rolling(232, min_periods=232).max()
        dd = lag / hi - 1.0
        pos = {d: i for i, d in enumerate(idx)}
        for k, t in enumerate(rebalance_dates[:-1]):
            i = pos.get(t)
            if i is None or pd.isna(dd.iloc[i]):
                continue
            entry_i = i + 1
            next_t = rebalance_dates[k + 1]
            j = pos.get(next_t)
            if entry_i >= len(idx) or j is None or j + 1 >= len(idx):
                continue
            entry_price, exit_price = float(open_.iloc[entry_i]), float(open_.iloc[j + 1])
            if entry_price <= 0 or exit_price <= 0:
                continue
            monthly_returns.setdefault(t, []).append(exit_price / entry_price - 1.0)

    snapshots = [(START, TOTAL_CAPITAL)]
    equity = TOTAL_CAPITAL
    for k, t in enumerate(rebalance_dates[:-1]):
        rets = monthly_returns.get(t)
        if not rets:
            continue
        equity *= (1.0 + float(np.mean(rets)))
        snapshots.append((rebalance_dates[k + 1], equity))
    return snapshots


def annual_log_returns(snapshots):
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


def truncate_snapshots(snapshots, max_year):
    return [(d, e) for d, e in snapshots if int(d[:4]) <= max_year]


def load_sector_lookup():
    with open(SECTOR_MAP_PATH, encoding="utf-8") as f:
        smap = json.load(f)["mapping"]
    lookup = {}
    for path in (UNIVERSE_A1A, UNIVERSE_A1B):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                raw_sector = row.get("sector")
                lookup[row["ticker"]] = smap.get(raw_sector, "기타(미매핑)")
    return lookup


def classify_regime_by_year(kospi_path):
    kospi = pd.read_parquet(kospi_path).sort_values("date")
    kospi["date"] = kospi["date"].astype(str)
    kospi = kospi.set_index("date")["value"]
    yearly_regime = {}
    years = sorted({d[:4] for d in kospi.index})
    for y in years:
        start_val = kospi[kospi.index >= f"{y}-01-01"].iloc[0] if any(kospi.index >= f"{y}-01-01") else None
        end_candidates = kospi[kospi.index <= f"{y}-12-31"]
        end_val = end_candidates.iloc[-1] if len(end_candidates) else None
        if start_val is None or end_val is None:
            continue
        ret = end_val / start_val - 1.0
        if ret >= 0.10:
            regime = "bull"
        elif ret <= -0.10:
            regime = "bear"
        else:
            regime = "sideways"
        yearly_regime[int(y)] = {"kospiYearReturn": round(float(ret), 4), "regime": regime}
    return yearly_regime


def main():
    t0 = time.time()
    print("running DD252 gross + BM1 (full monthly snapshots + closed positions)...")
    dd_snapshots, dd_closed, bars_by_ticker, calendar = run_dd252_gross()
    bm1_snapshots = build_bm1(bars_by_ticker, calendar)
    print(f"DD252 months={len(dd_snapshots)}, BM1 months={len(bm1_snapshots)}, "
          f"DD252 closed positions={len(dd_closed)} ({time.time()-t0:.0f}s)")

    # ---- 1. 2026 제외 성과 ----
    dd_ex26 = truncate_snapshots(dd_snapshots, 2025)
    bm1_ex26 = truncate_snapshots(bm1_snapshots, 2025)
    m_dd_full, m_dd_ex26 = curve_metrics(dd_snapshots), curve_metrics(dd_ex26)
    m_bm1_full, m_bm1_ex26 = curve_metrics(bm1_snapshots), curve_metrics(bm1_ex26)
    print("\n[1] 2026 포함/제외")
    print(f"  DD252  full: CAGR={m_dd_full['cagr']:.4f} MDD={m_dd_full['mdd']:.4f} Sharpe={m_dd_full['sharpe']}")
    print(f"  DD252 ex-26: CAGR={m_dd_ex26['cagr']:.4f} MDD={m_dd_ex26['mdd']:.4f} Sharpe={m_dd_ex26['sharpe']}")
    print(f"  BM1    full: CAGR={m_bm1_full['cagr']:.4f} MDD={m_bm1_full['mdd']:.4f} Sharpe={m_bm1_full['sharpe']}")
    print(f"  BM1   ex-26: CAGR={m_bm1_ex26['cagr']:.4f} MDD={m_bm1_ex26['mdd']:.4f} Sharpe={m_bm1_ex26['sharpe']}")

    # ---- 2. 연도별 로그초과수익 ----
    dd_log = annual_log_returns(dd_snapshots)
    bm1_log = annual_log_returns(bm1_snapshots)
    years = sorted(set(dd_log) & set(bm1_log))
    excess = {y: dd_log[y] - bm1_log[y] for y in years}
    total_excess = sum(excess.values())
    share = {y: round(v / total_excess, 4) if total_excess else None for y, v in excess.items()}
    print("\n[2] 연도별 로그초과수익(DD252-BM1) 및 비중")
    for y in years:
        print(f"  {y}: dd={dd_log[y]:.4f} bm1={bm1_log[y]:.4f} excess={excess[y]:.4f} share={share[y]}")
    print(f"  총초과 로그수익: {total_excess:.4f}")

    # ---- 3. 국면별 성과 ----
    regime_by_year = classify_regime_by_year(KOSPI_PATH)
    regime_bucket = defaultdict(lambda: {"ddLog": 0.0, "bm1Log": 0.0, "years": []})
    for y in years:
        r = regime_by_year.get(y, {}).get("regime", "unknown")
        regime_bucket[r]["ddLog"] += dd_log[y]
        regime_bucket[r]["bm1Log"] += bm1_log[y]
        regime_bucket[r]["years"].append(y)
    print("\n[3] KOSPI 연간수익률 기준 국면별 성과 (연 로그수익 합산)")
    for r, v in regime_bucket.items():
        print(f"  {r} ({v['years']}): DD252 logSum={v['ddLog']:.4f}, BM1 logSum={v['bm1Log']:.4f}, "
              f"excess={v['ddLog']-v['bm1Log']:.4f}")
    print("  연도별 KOSPI 국면:", {y: regime_by_year.get(y) for y in years})

    # ---- 4. 종목 집중도 ----
    pnl_by_ticker = defaultdict(float)
    for p in dd_closed:
        pnl_by_ticker[p["symbol"]] += p["pnl"]
    total_pnl = sum(pnl_by_ticker.values())
    ranked = sorted(pnl_by_ticker.items(), key=lambda kv: kv[1], reverse=True)
    top5_share = sum(v for _, v in ranked[:5]) / total_pnl if total_pnl else None
    top10_share = sum(v for _, v in ranked[:10]) / total_pnl if total_pnl else None
    top20_share = sum(v for _, v in ranked[:20]) / total_pnl if total_pnl else None
    print(f"\n[4] 종목 집중도 - 전체 {len(pnl_by_ticker)}종목, 총pnl={total_pnl:.0f}")
    print(f"  top5={top5_share}, top10={top10_share}, top20={top20_share}")
    print("  top10 종목:", ranked[:10])

    # ---- 5. 2019/2023 업종 분해 ----
    sector_lookup = load_sector_lookup()
    print("\n[5] 2019/2023 진입 종목 업종 구성")
    for target_year in (2019, 2023):
        year_entries = [p for p in dd_closed if p["entry_date"][:4] == str(target_year)]
        sector_counts = Counter(sector_lookup.get(p["symbol"], "미매핑") for p in year_entries)
        year_pnl = sum(p["pnl"] for p in year_entries)
        print(f"  {target_year}: {len(year_entries)}건 진입, 총pnl={year_pnl:.0f}")
        print(f"    업종분포: {dict(sector_counts.most_common())}")
    overall_sector_counts = Counter(sector_lookup.get(p["symbol"], "미매핑") for p in dd_closed)
    print(f"  전체기간 업종분포(참고): {dict(overall_sector_counts.most_common())}")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-27-dd252-arm-a-decomposition")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "dd252-arm-a-decomposition.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "DD252 Arm A - 구조적 alpha vs 국면노출 분해. 사용자 지시 2026-08-27.",
            "excludeing2026": {"dd252Full": m_dd_full, "dd252Ex2026": m_dd_ex26,
                                "bm1Full": m_bm1_full, "bm1Ex2026": m_bm1_ex26},
            "annualLogExcess": {"dd252LogByYear": dd_log, "bm1LogByYear": bm1_log,
                                 "excessByYear": excess, "shareOfTotalExcess": share,
                                 "totalExcessLogReturn": total_excess},
            "regimeByYear": regime_by_year,
            "regimeBucketSummary": {r: {"ddLogSum": v["ddLog"], "bm1LogSum": v["bm1Log"],
                                        "excess": v["ddLog"] - v["bm1Log"], "years": v["years"]}
                                     for r, v in regime_bucket.items()},
            "tickerConcentration": {"nTickers": len(pnl_by_ticker), "totalPnl": total_pnl,
                                     "top5Share": top5_share, "top10Share": top10_share,
                                     "top20Share": top20_share, "top10Tickers": ranked[:10]},
        }, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path, f"(total {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
