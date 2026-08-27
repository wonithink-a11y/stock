#!/usr/bin/env python
"""DD252(skip-1m) Arm A(baseline) — 진짜 6-cohort 격리 회계용 오프라인 선정.

findings/dd252-strategy-design-2026-08.md §7·§8·§13(Arm A)를 그대로 따른다:
  - 신호: dd_252_skip1m = close[t-21]/max(close[t-252..t-21]) - 1, 내림차순 top-30
  - Arm A는 유동성 필터 없음(§13 - amt20 필터는 Arm C 전용, 이 단계에서 안 씀)
  - 유니버스: A1A_A1B_MERGED, 자격 = 히스토리 273세션 이상 + 신호 유효
  - 6개 staggered cohort, 매월 정확히 1개 cohort만 교체(cohort_idx = 월인덱스 % 6)
  - 보유 120세션 고정, "신규 cohort에서는 동일 종목을 중복 선정하지 않음(다음
    순위 종목으로 채움)"(§7) — 이 중복배제가 이 스크립트의 핵심 로직이다.

각 cohort의 "현재 보유 중"은 이 오프라인 워크포워드가 직접 추적한다(진짜 포트폴리오
회계가 아니라 선정 단계의 예약 장부) — 실제 현금·주식수 회계는 run_dd252_
cohort_smoke.py가 6개 독립 Portfolio로 따로 한다. 이 스크립트는 "이번 달 이
cohort에 넣을 30종목이 무엇인가"만 정한다.

만기 판정: entry_session = calendar.next_session(신호일 t) (엔진의 실제 진입일과
동일 규칙), expiry_session = 그로부터 120번째 세션(next_n_sessions(entry_session,
120)의 마지막) — "그 날짜까지는 아직 보유 중"으로 본다. 이후 재선정 가능.

  python build_selection_cohort.py [--end YYYY-MM-DD]
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_STRATEGY_LAB_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
sys.path.insert(0, _STRATEGY_LAB_DIR)

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.a2bProvider import A2bProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(_STRATEGY_LAB_DIR))
START = "2016-01-01"
END = sys.argv[sys.argv.index("--end") + 1] if "--end" in sys.argv else "2026-08-03"
TOP_N = 30
HOLD_SESSIONS = 120
MIN_HISTORY = 273  # 252 + 21 skip
N_COHORTS = 6


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def load_merged_bars(calendar):
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=True)
    a1b_tickers = {e.ticker for e in universe.entries if e.source == "A1B"}
    print(f"Universe: {len(universe.tickers)} tickers (A1A_A1B_MERGED, A1B={len(a1b_tickers)})")

    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(set(universe.tickers), START, END, universe_hash=universe.universe_hash)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}

    if a1b_tickers:
        a2b = A2bProvider(repo_root=REPO_ROOT)
        a2b_raw = a2b.load(a1b_tickers, START, END, universe_hash=universe.universe_hash)
        for t, df in a2b_raw.items():
            if not df.empty:
                bars_by_ticker[t] = _drop_suspension_rows(df)
    print(f"bars loaded: {len(bars_by_ticker)} tickers")
    return bars_by_ticker


def build_dd_panel(bars_by_ticker, rebalance_dates):
    rows = []
    for ticker, bars in bars_by_ticker.items():
        if bars.empty or len(bars) < MIN_HISTORY:
            continue
        close = bars["close"]
        idx = close.index.astype(str)
        lag = close.shift(21)
        hi = lag.rolling(232, min_periods=232).max()
        dd = lag / hi - 1.0
        pos = {d: i for i, d in enumerate(idx)}
        for t in rebalance_dates:
            i = pos.get(t)
            if i is None:
                continue
            val = dd.iloc[i]
            if pd.isna(val):
                continue
            rows.append({"ticker": ticker, "asOf": t, "dd_252_skip1m": float(val)})
    panel = pd.DataFrame(rows)
    return {asOf: g.sort_values("dd_252_skip1m", ascending=False)["ticker"].tolist()
            for asOf, g in panel.groupby("asOf")}


def main():
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    bars_by_ticker = load_merged_bars(calendar)
    rebalance_dates = monthly_rebalance_dates(calendar, START, END)
    ranked_by_month = build_dd_panel(bars_by_ticker, rebalance_dates)
    print(f"months with eligible panel: {len(ranked_by_month)}/{len(rebalance_dates)}")

    # cohort_open[c]: {ticker: expirySession(str)} - "아직 보유 중"으로 취급하는 만기일
    cohort_open = [dict() for _ in range(N_COHORTS)]
    selection = {}  # ticker -> [{"date","holdSessions","cohort"}, ...]
    monthly_diag = []

    for month_idx, t in enumerate(rebalance_dates):
        cohort_idx = month_idx % N_COHORTS

        # 만기 처리 - 모든 cohort에 대해(달력 드리프트로 정확히 6개월 간격이
        # 아닐 수 있으니 "이번 달 차례인 cohort"만 보지 않는다).
        for c in range(N_COHORTS):
            expired = [tk for tk, exp in cohort_open[c].items() if exp < t]
            for tk in expired:
                del cohort_open[c][tk]

        if t not in ranked_by_month:
            monthly_diag.append({"date": t, "cohort": cohort_idx, "selected": 0, "skippedDup": 0})
            continue

        held_anywhere = set()
        for c in range(N_COHORTS):
            held_anywhere |= set(cohort_open[c].keys())

        entry_session = calendar.next_session(t)
        if entry_session is None:
            continue
        exit_window = calendar.next_n_sessions(entry_session, HOLD_SESSIONS)
        expiry = exit_window[-1] if len(exit_window) == HOLD_SESSIONS else None
        if expiry is None:
            # 달력 끝에 너무 가까워 120세션을 다 못 채움 - 이 달은 신규 진입 안 함
            monthly_diag.append({"date": t, "cohort": cohort_idx, "selected": 0, "skippedDup": 0,
                                  "note": "calendar tail - insufficient sessions for full hold"})
            continue

        # 슬롯 캡 - 120세션이 6개월(달력)을 넘기는 달(설·추석 연휴로 거래일 밀도가
        # 낮은 구간을 지날 때 발생, 실측: 코호트2 2018/2019/2025년 3월 등)에는 이
        # cohort의 직전 배치가 아직 안 끝나 있다. 그 상태에서도 항상 TOP_N=30을
        # 새로 채우려 하면 엔진 Portfolio의 max_positions=30을 넘겨 tie-break(종목
        # 코드 오름차순)가 DD252 순위와 무관하게 임의로 잘라낸다(실측: 최대
        # 30종목 중 29종목이 이렇게 통째로 버려진 사례 있음). 남은 슬롯만큼만
        # 새로 뽑아 애초에 엔진 슬롯을 절대 못 넘기게 한다 - 이번 로테이션이
        # 30종목 미만이 되는 대신, 뽑히는 종목은 항상 DD252 순위 상위다.
        slots_available = max(0, TOP_N - len(cohort_open[cohort_idx]))

        selected, skipped_dup = [], 0
        for tk in ranked_by_month[t]:
            if tk in held_anywhere:
                skipped_dup += 1
                continue
            selected.append(tk)
            if len(selected) >= slots_available:
                break

        for tk in selected:
            cohort_open[cohort_idx][tk] = expiry
            selection.setdefault(tk, []).append(
                {"date": t, "holdSessions": HOLD_SESSIONS, "cohort": cohort_idx})

        monthly_diag.append({"date": t, "cohort": cohort_idx, "selected": len(selected),
                              "skippedDup": skipped_dup, "slotsAvailable": slots_available,
                              "cohortOpenBefore": len(cohort_open[cohort_idx]) - len(selected)})

    for tk in selection:
        selection[tk].sort(key=lambda e: e["date"])

    avg_selected = sum(d["selected"] for d in monthly_diag) / len(monthly_diag) if monthly_diag else None
    total_dup_skips = sum(d["skippedDup"] for d in monthly_diag)
    print(f"avg selected/month={avg_selected:.1f}, total cross-cohort dedup skips={total_dup_skips}")

    out_path = os.path.join(_THIS_DIR, "selection.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection_cohort.py",
            "arm": "A (baseline, no liquidity filter per design doc §13)",
            "period": f"{START} ~ {END}",
            "topN": TOP_N, "holdSessions": HOLD_SESSIONS, "nCohorts": N_COHORTS,
            "minHistorySessions": MIN_HISTORY,
            "rebalanceMonths": len(rebalance_dates),
            "avgSelectedPerMonth": round(avg_selected, 2) if avg_selected is not None else None,
            "totalCrossCohortDedupSkips": total_dup_skips,
            "tickersEverSelected": len(selection),
            "monthlyDiagnostics": monthly_diag,
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {out_path} ({len(selection)} tickers, {len(rebalance_dates)} months)")


if __name__ == "__main__":
    main()
