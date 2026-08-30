#!/usr/bin/env python
"""Offline builder for pbr_value_v1_dropout's selection.json - identical data
pipeline to strategies/pbr_value_v1/build_selection.py (same valuation panel,
same liquidity threshold, same top-N), but the selection step itself is
different: instead of re-picking the top-30 by PBR from scratch every month
(pbr_value_v1's approach - full turnover regardless of last month's holdings),
this follows Qlib's TopkDropoutStrategy pattern - each month, keep whichever
currently-held names are still ranked well enough, and only replace the
worst-ranked n_drop of them with fresh top candidates.

Why this is worth testing (findings/github-strategy-sources-usability-2026-08.md):
pbr_value_v1/build_selection.py never looks at the previous month's selection
at all - every rebalance is a clean-slate top-30 cut. That's the one thing
this project hasn't tried for PBR: does capping monthly turnover to n_drop
names (instead of however many names cross the top-30 line, which can be much
higher) reduce round-trip costs enough to matter?

Algorithm per rebalance month (state carried forward as `held`):
  1. Rank this month's eligible tickers (turnover20 >= MIN_TURNOVER) by PBR
     ascending - same eligibility rule as pbr_value_v1, unchanged.
  2. Of last month's `held` set, keep only those still eligible this month
     (a name that becomes illiquid or delists just falls out - that's not a
     "drop" in the n_drop sense, there's no candidate to weigh it against).
  3. Sort those still-eligible held names by this month's rank (best first).
     If there are more than (TOP_N - N_DROP) of them, drop the worst ones
     down to that count - this is the only place turnover gets forced.
  4. Fill up to TOP_N with the best-ranked names not already kept.
  5. `held` becomes this month's selection; continue to next month.

First month: `held` is empty, so this degenerates to exactly pbr_value_v1's
plain top-30 cut - the two strategies start identically and only diverge
from month 2 onward.

  python build_selection_dropout.py
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # .../strategies/pbr_value_v1_dropout
_STRATEGY_LAB_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # .../research/strategy-lab
sys.path.insert(0, _STRATEGY_LAB_DIR)

import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(_STRATEGY_LAB_DIR))
VALUATION_PANEL = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                                "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
START = "2016-01-01"
END = sys.argv[sys.argv.index("--end") + 1] if "--end" in sys.argv else "2026-08-14"
TOP_N = 30
N_DROP = 3  # policy.json factor.nDrop과 맞춰야 한다 (문서화만, 코드가 policy.json을 읽지는 않음 - build_selection.py 원본도 그렇다)
MIN_TURNOVER = 100_000_000.0


def monthly_rebalance_dates(calendar, start, end):
    days = calendar.sessions_between(start, end)
    out, seen = [], set()
    for d in days:
        ym = d[:7]
        if ym not in seen:
            seen.add(ym)
            out.append(d)
    return out


def next_selection(held, ranked, top_n, n_drop):
    """한 달치 dropout 선택 - main()의 루프 본문과 동일 로직을 독립 함수로
    뽑아 selftest가 실제 데이터 없이 검증할 수 있게 한다.
    held: 지난달 선택(순위 무관, 순서 무관) 리스트.
    ranked: 이번 달 적격 종목을 PBR 오름차순으로 정렬한 리스트."""
    rank_of = {t: i for i, t in enumerate(ranked)}
    still_eligible_held = sorted((t for t in held if t in rank_of), key=lambda t: rank_of[t])
    keep_count = max(0, top_n - n_drop)
    kept = still_eligible_held[:keep_count]
    kept_set = set(kept)
    filled = [t for t in ranked if t not in kept_set][:top_n - len(kept)]
    return kept + filled


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    # 1) 첫 달(held=[])은 순수 top-N 컷과 동일해야 한다
    ranked1 = [f"T{i}" for i in range(10)]
    sel1 = next_selection([], ranked1, top_n=5, n_drop=2)
    check("첫 달은 순수 top-N과 동일", sel1 == ranked1[:5])

    # 2) 순위 변동이 없으면 아무것도 안 바뀐다(교체 0건)
    sel2 = next_selection(sel1, ranked1, top_n=5, n_drop=2)
    check("변동 없으면 그대로 유지", set(sel2) == set(sel1))

    # 3) 보유 5종목 중 하위 2개가 top-N 밖으로 밀려나면 정확히 2개만 교체된다
    held3 = ["T0", "T1", "T2", "T3", "T4"]  # 이전 보유
    ranked3 = ["T5", "T6", "T0", "T1", "T2", "T3", "T4", "T7", "T8", "T9"]
    # T3, T4가 순위 5, 6위(0-indexed)로 top-5 밖 - 하위 2개라 nDrop=2로 정확히 교체 대상
    sel3 = next_selection(held3, ranked3, top_n=5, n_drop=2)
    dropped = set(held3) - set(sel3)
    added = set(sel3) - set(held3)
    check("교체는 정확히 nDrop(2)건", len(dropped) == 2 and len(added) == 2)
    check("교체된 건 보유 중 최하위 랭크(T3,T4)", dropped == {"T3", "T4"})
    check("새로 들어온 건 최상위 미보유 후보(T5,T6)", added == {"T5", "T6"})

    # 4) 보유 종목이 이번 달 유니버스에서 아예 사라지면(유동성 미달 등)
    #    nDrop 예산과 무관하게 자동 이탈한다
    held4 = ["T0", "T1", "T2", "T3", "T4"]
    ranked4 = ["T5", "T6", "T7", "T0", "T1"]  # T2,T3,T4는 이번 달 후보 자체에 없음(강제이탈 3건)
    sel4 = next_selection(held4, ranked4, top_n=5, n_drop=2)
    check("적격 후보에서 사라진 종목은 nDrop과 무관하게 전부 이탈",
          set(sel4) & {"T2", "T3", "T4"} == set())
    check("사라진 자리는 신규 후보로 채워져도 top_n을 유지", len(sel4) == 5)

    # 5) 선택 크기는 항상 min(top_n, 후보수)
    sel5 = next_selection([], ["A", "B"], top_n=5, n_drop=2)
    check("후보가 top_n보다 적으면 있는 만큼만", sel5 == ["A", "B"])

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print(f"\n통과 {sum(c for _, c in checks)} · 실패 {sum(not c for _, c in checks)}")
    return 0 if ok else 1


def main():
    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = sorted(val["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers, START, END, universe_hash="pbr-value-v1-dropout-selection")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers")

    rebalance_dates = monthly_rebalance_dates(calendar, START, END)

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
    print(f"turnover rows={len(turnover_df)}")

    merged = val.merge(turnover_df, on=["ticker", "asOf"], how="inner")
    eligible = merged[merged["turnover20"] >= MIN_TURNOVER]
    print(f"eligible (pbr>0 & turnover20>={MIN_TURNOVER:,.0f}) rows={len(eligible)}")

    # holdSessions - pbr_value_v1/build_selection.py와 동일 계산(무변경 복사).
    hold_sessions_by_date = {}
    for k, t in enumerate(rebalance_dates[:-1]):
        entry_date = calendar.next_session(t)
        next_rebal = rebalance_dates[k + 1]
        exit_target = calendar.next_session(next_rebal)
        if entry_date is None or exit_target is None:
            continue
        hold_sessions_by_date[t] = len(calendar.sessions_between(entry_date, exit_target))
    if rebalance_dates:
        last_t = rebalance_dates[-1]
        hold_sessions_by_date.setdefault(last_t, 21)

    # ---- dropout 선택 루프 (pbr_value_v1/build_selection.py와 다른 유일한 부분) ----
    eligible_by_month = {asOf: g.sort_values("pbr", ascending=True)["ticker"].tolist()
                          for asOf, g in eligible.groupby("asOf")}

    selection = {}
    monthly_counts = {}
    monthly_replaced = {}  # 진단용: 매달 실제로 교체된 종목 수
    held = []  # 순위순 정렬된 현재 보유 리스트(최선 랭크 먼저)

    for asOf in rebalance_dates:
        if asOf not in hold_sessions_by_date or asOf not in eligible_by_month:
            continue
        ranked = eligible_by_month[asOf]
        new_selection = next_selection(held, ranked, TOP_N, N_DROP)

        monthly_replaced[asOf] = len(set(new_selection) - set(held))
        monthly_counts[asOf] = len(new_selection)

        for ticker in new_selection:
            selection.setdefault(ticker, []).append(
                {"date": asOf, "holdSessions": hold_sessions_by_date[asOf]})

        held = new_selection

    for ticker in selection:
        selection[ticker].sort(key=lambda e: e["date"])

    avg_replaced = round(sum(monthly_replaced.values()) / len(monthly_replaced), 2) if monthly_replaced else None
    print(f"월평균 신규교체 종목수: {avg_replaced} (nDrop 상한={N_DROP})")

    out_path = os.path.join(_THIS_DIR, "selection.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_selection_dropout.py",
            "sourcePanel": os.path.relpath(VALUATION_PANEL, REPO_ROOT),
            "period": f"{START} ~ {END}",
            "topN": TOP_N,
            "nDrop": N_DROP,
            "minTurnover": MIN_TURNOVER,
            "rebalanceMonths": len(monthly_counts),
            "avgSelectedPerMonth": round(sum(monthly_counts.values()) / len(monthly_counts), 1) if monthly_counts else None,
            "avgReplacedPerMonth": avg_replaced,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=2)
    print(f"saved: {out_path} ({len(selection)} tickers, {len(monthly_counts)} months)")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()
