#!/usr/bin/env python
"""PBR top-N 실험의 플라시보 대조 (연구 샌드박스).

'TRAIN에서 선택된 topN=100'이 실제로 PBR 랭킹 정보를 이용하는 힘이 있는지,
아니면 같은 보유 구조의 무작위 선택(topN 그리드가 이미 다중비교를 하고 있어
그중 하나는 우연히 TRAIN 1위를 찍을 수 있음)과 구분되는지 확인한다.

방법: 같은 기간·같은 유니버스·같은 유동성 임계값에서 매달 적격 종목의 PBR
순위를 그 자리에서 셔플(해당 달 내 permutation null)한 뒤 상위 100개를 고른
플라시보 선택을 만든다 - 저PBR 신호의 정보가 0이어도 같은 topN 구조가 남는다.
그걸 같은 엔진·같은 MTM·같은 TRAIN/VALID/TEST 분할로 돌려 관측 분포 대조로
남긴다. 저PBR 신호가 진짜 정보를 가지면 플라시보가 잘라내야 할 만큼 본 실험이
위에 있어야 하고, 그 격차가 안 나면 신호 기여가 플라시보 수준임을 뜻한다.

  python run_pbr_topn_placebo_oos.py
"""
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from run_pbr_topn_strength_oos import (  # noqa: E402
    REPO_ROOT, START, END, MIN_TURNOVER, TOP_N_GRID, SPLIT_FRACTIONS,
    OUT_DIR, PBR_POLICY, monthly_rebalance_dates, make_rule_module,
    split_snapshots, monthly_return_tstats,
)
from pbr_vs_ew_monthly_mtm import schedule_with_monthly_mtm, curve_metrics  # noqa: E402
from engine.runner import run_smoke  # noqa: E402
from engine.portfolio.portfolio import PortfolioConfig  # noqa: E402

PLACEBO_TOP_N = 100   # TRAIN에서 선택된 topN (동일 보유 구조에서 신호만 제거)
SEED = 20260906


def main():
    t0 = time.time()
    with open(PBR_POLICY, encoding="utf-8") as f:
        params = json.load(f)

    # run_pbr_topn_strength_oos와 같은 바/bars 로딩을 재사용하려면 그 쪽 로직을
    # 그대로 가져온다 - 여기서는 핵심 데이터만 다시 만들고 셔플 선택만 다르게 한다.
    from engine.data.calendar import TradingCalendar  # noqa: E402
    from engine.data.a2aProvider import A2aProvider  # noqa: E402
    from engine.runner import _drop_suspension_rows  # noqa: E402
    from run_pbr_topn_strength_oos import VALUATION_PANEL

    val = pd.DataFrame([json.loads(line) for line in open(VALUATION_PANEL, encoding="utf-8")])
    val = val.dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]

    tickers = sorted(val["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    rng = random.Random(SEED)

    # --- 매달 적격 종목 PBR 순위 셔플(해당 달 내 permutation) 후 상위 N ---
    # 유동성(turnover20)은 그 달 고정이고 PBR 순위만 섞는다 - '저PBR인가' 정보를
    # 제거한 플라시보 선택.
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in a2a.load(
        sorted(val["ticker"].unique()), START, END, universe_hash="pbr-topn-placebo-oos").items()}
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

    selection_by_ticker = {}
    eligible_by_month = {}
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
            eligible_by_month.setdefault(t, []).append({"ticker": ticker, "asOf": t, "turnover20": float(tv)})

    for asOf, rows in eligible_by_month.items():
        if asOf not in hold_sessions_by_date:
            continue
        eligible_ticks = [r["ticker"] for r in rows]
        rng.shuffle(eligible_ticks)
        chosen = eligible_ticks[:PLACEBO_TOP_N]
        for tk in chosen:
            selection_by_ticker.setdefault(tk, []).append(
                {"date": asOf, "holdSessions": hold_sessions_by_date[asOf]})
    for tk in selection_by_ticker:
        selection_by_ticker[tk].sort(key=lambda e: e["date"])

    print(f"placebo selection topN={PLACEBO_TOP_N} (seed={SEED}): "
          f"{len(selection_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    rule = make_rule_module(params, selection_by_ticker, PLACEBO_TOP_N)
    base = run_smoke("pbr_topn_placebo", START, END, REPO_ROOT, rule_module=rule,
                     ticker_subset=sorted(selection_by_ticker.keys()))
    portfolio_cfg = PortfolioConfig(
        initial_capital=rule.PARAMS["portfolio"]["initialCapital"],
        max_positions=rule.PARAMS["portfolio"]["maxPositions"],
        equal_weight=rule.PARAMS["portfolio"]["equalWeight"],
        fractional_shares=rule.PARAMS["portfolio"]["fractionalShares"],
        tie_break=rule.PARAMS["portfolio"]["tieBreak"])
    portfolio, snaps_full = schedule_with_monthly_mtm(
        base["resolved"], portfolio_cfg, base["bars_by_ticker"], base["calendar"], START, END)
    by_split = split_snapshots(snaps_full)
    trades = [p for p in portfolio.closed_positions if "pnl" in p]
    wins = [p for p in trades if p["pnl"] > 0]
    split_metrics = {name: curve_metrics(snaps) for name, snaps in by_split.items()}
    tstat_zero = monthly_return_tstats(snaps_full)
    ew_base = run_smoke("ew_benchmark_liquid_v1", START, END, REPO_ROOT)
    ew_cfg = PortfolioConfig(
        initial_capital=ew_base["params"]["portfolio"]["initialCapital"],
        max_positions=ew_base["params"]["portfolio"]["maxPositions"],
        equal_weight=ew_base["params"]["portfolio"]["equalWeight"],
        fractional_shares=ew_base["params"]["portfolio"]["fractionalShares"],
        tie_break=ew_base["params"]["portfolio"]["tieBreak"])
    ew_portfolio, ew_snaps = schedule_with_monthly_mtm(
        ew_base["resolved"], ew_cfg, ew_base["bars_by_ticker"], ew_base["calendar"], START, END)
    tstat_vs_ew = monthly_return_tstats(snaps_full, ew_snaps)

    result = {
        "placeboTopN": PLACEBO_TOP_N, "seed": SEED,
        "method": "per-month permutation null on PBR rank (keep liquidity+holdSessions structure), same engine/MTM/split",
        "fullPeriod": curve_metrics(snaps_full),
        "bySplit": split_metrics,
        "closedPositionCount": len(trades),
        "winRate": round(len(wins) / len(trades), 4) if trades else None,
        "tstatVsZeroFull": tstat_zero, "tstatVsEWFull": tstat_vs_ew,
    }
    print(json.dumps({"fullPeriod": result["fullPeriod"], "bySplit": {
        k: {"sharpe": v["sharpe"]} for k, v in split_metrics.items()},
        "winRate": result["winRate"], "N": result["closedPositionCount"],
        "tstatVsEW": result["tstatVsEWFull"]}, ensure_ascii=False, indent=2, default=str))

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "pbr-topn-placebo.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PBR top-N 실험 플라시보 대조 - TRAIN 선택 topN=100에 대해 "
                       "매달 PBR 순위 셔플(permutation null)의 보유 구조를 같은 엔진/MTM으로 실행.",
            "result": result,
        }, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)


if __name__ == "__main__":
    main()