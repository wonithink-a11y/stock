#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""5DC-v1A-P — 정제 Risk-Off 필터 실제 runner 검증.

배경: `findings/vix-incremental-info-check-2026-08.md`(P1-1)가 Risk-Off
구간 안에서도 vixState별 성과가 크게 갈린다는 걸 발견했다(VIX Low인 Risk-Off
가 가장 나쁘고, VIX High인 Risk-Off는 오히려 승률·평균PnL이 플러스로
반전). 이 스크립트는 그 관측이 실제 필터 가치로 이어지는지 검증한다 -
`5dc_riskoff_runner_validation.py`(원본 필터: "regime==Risk-Off면 전부
차단")를 최소 수정해 조건을 **"regime==Risk-Off AND vixState in
(Low, Mid)"**로 좁힌다(VIX High인 Risk-Off는 더 이상 차단하지 않음).

새 임계값 없음 - vixState 자체가 이미 기존 production 임계값(<20/20-30/
>=30)이고 regime 라벨도 기존 그대로다. 바뀐 건 "언제 차단할지"를 결정하는
**조합 규칙**뿐이다.

원본 `5dc_riskoff_runner_validation.py`는 무변경 - 이 파일이 그 로직을
복제해 필터 조건 한 줄만 바꾼다.

  python 5dc_riskoff_vix_refined_runner_validation.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.metrics.metrics import trade_stats  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.runner import load_strategy  # noqa: E402
from run_5dc_v1a_p_merged import (  # noqa: E402
    _drop_suspension_rows, realized_pnl_metrics, run_5dc_pipeline,
    trades_from_portfolio, yearly_breakdown,
)

# 모듈명이 숫자로 시작해 일반 import 불가 - importlib으로 파일 경로 로드
# (5dc_riskoff_runner_validation.py 원본은 무변경, 읽기만 한다)
import importlib.util as _ilu  # noqa: E402

_spec = _ilu.spec_from_file_location(
    "_rv", os.path.join(os.path.dirname(os.path.abspath(__file__)), "5dc_riskoff_runner_validation.py"))
_rv = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_rv)
A2B_DIR, MRD, REPO_ROOT = _rv.A2B_DIR, _rv.MRD, _rv.REPO_ROOT
START, END = _rv.START, _rv.END
load_merged_bars_finalized = _rv.load_merged_bars_finalized

REPORTS_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports")


def load_pit_regime_vix_lookup():
    """regime과 vixState를 같이 반환 - vix-incremental-info-check-2026-08.md
    와 완전히 동일한 PIT 결합 규칙."""
    rl = pd.read_parquet(os.path.join(MRD, "regime_labels.parquet"))
    rl["usable"] = rl["usableFromDate"].astype(str)
    lab = rl[["usable", "regime", "vixState"]].sort_values("usable").reset_index(drop=True)
    usable_arr = lab["usable"].to_numpy()
    regime_arr = lab["regime"].to_numpy()
    vix_arr = lab["vixState"].to_numpy()

    def _fn(entry_date):
        j = np.searchsorted(usable_arr, entry_date, side="right") - 1
        if j < 0:
            return None, None
        return str(regime_arr[j]), str(vix_arr[j])

    return _fn


def schedule_portfolio_with_refined_filter(resolved, portfolio, portfolio_cfg, label_of, apply_filter):
    """5dc_riskoff_runner_validation.py::schedule_portfolio_with_riskoff_filter
    와 동일 구조 - 필터 조건만 "Risk-Off AND vixState in (Low, Mid)"로 좁힘."""
    by_entry_date, by_exit_date = {}, {}
    for item in resolved:
        _, order, entry_fill, exit_fill, _, _ = item
        by_entry_date.setdefault(order.order_date, []).append(item)
        by_exit_date.setdefault(exit_fill.fill_date, []).append(item)

    event_dates = sorted(set(by_entry_date) | set(by_exit_date))
    max_open_seen = 0
    blocked_count = 0

    def _check_invariant():
        assert len(portfolio.open_positions) <= portfolio_cfg.max_positions
        return len(portfolio.open_positions)

    for date in event_dates:
        exits_today, same_bar_exit_candidates = [], []
        for item in by_exit_date.get(date, []):
            sig, order, entry_fill, exit_fill, _, _ = item
            if order.symbol in portfolio.open_positions:
                shares = portfolio.open_positions[order.symbol]["shares"]
                exits_today.append((order.symbol, exit_fill, shares))
            elif order.order_date == date:
                same_bar_exit_candidates.append((order.symbol, exit_fill))

        candidates_today = []
        for (_, order, entry_fill, _, _, _) in by_entry_date.get(date, []):
            regime, vix = label_of(order.order_date)
            should_block = apply_filter and regime == "Risk-Off" and vix in ("Low", "Mid")
            if should_block:
                blocked_count += 1
                continue
            candidates_today.append((order, entry_fill))

        portfolio.process_day(date, exits_today, candidates_today)
        max_open_seen = max(max_open_seen, _check_invariant())

        if same_bar_exit_candidates:
            same_bar_exits_admitted = [
                (symbol, exit_fill, portfolio.open_positions[symbol]["shares"])
                for symbol, exit_fill in same_bar_exit_candidates
                if symbol in portfolio.open_positions
            ]
            if same_bar_exits_admitted:
                portfolio.process_day(date, same_bar_exits_admitted, [])
                max_open_seen = max(max_open_seen, _check_invariant())

    return max_open_seen, blocked_count


def run_variant(rule, universe, bars_by_ticker, price_provider, label_of, apply_filter, label):
    t0 = time.time()
    params = rule.PARAMS
    base = run_5dc_pipeline(REPO_ROOT, START, END, rule, universe, bars_by_ticker, price_provider)
    resolved = base["resolved"]

    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"],
        fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"],
    )
    portfolio = Portfolio(portfolio_cfg)
    max_open, blocked = schedule_portfolio_with_refined_filter(
        resolved, portfolio, portfolio_cfg, label_of, apply_filter)

    trades = trades_from_portfolio(portfolio)
    t_stats = trade_stats(trades)
    realized = realized_pnl_metrics(portfolio, START, END)
    print("  [%s] %d resolved-eligible, %d closed, blocked_entries=%d (%.0fs)"
          % (label, len(resolved), len(trades), blocked, time.time() - t0))
    return {
        "label": label, "resolvedEligibleCount": len(resolved),
        "closedPositionCount": len(trades), "blockedEntryCount": blocked,
        "resultTable": {**{k: v for k, v in t_stats.items()},
                        "finalEquity": realized["finalEquity"], "totalReturn": realized["totalReturn"],
                        "cagr": realized["cagr"], "mdd": realized["mdd"], "sharpe": realized["sharpe"],
                        "calmar": realized["calmar"]},
        "yearlyBreakdown": yearly_breakdown(trades),
    }


def main():
    t0 = time.time()
    rule = load_strategy("5dc_v1a_p", REPO_ROOT)
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=True)
    bars_raw, provider, n_excluded = load_merged_bars_finalized(REPO_ROOT, universe, START, END)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print("bars loaded: %d tickers (a2b qualityExcluded=%d) (%.0fs)"
          % (len(bars_by_ticker), n_excluded, time.time() - t0))

    label_of = load_pit_regime_vix_lookup()

    print("\n=== A. baseline (필터 없음) ===")
    variant_a = run_variant(rule, universe, bars_by_ticker, provider, label_of, False, "A_baseline")
    print("=== C. 정제 필터 (Risk-Off AND VIX Low/Mid만 차단) ===")
    variant_c = run_variant(rule, universe, bars_by_ticker, provider, label_of, True, "C_riskoff_vix_refined")

    a, c = variant_a["resultTable"], variant_c["resultTable"]
    print("\n[결과]")
    print("  A baseline       : trades=%d CAGR=%s MDD=%s PF=%s winRate=%s finalEquity=%s"
          % (variant_a["closedPositionCount"], a["cagr"], a["mdd"], a.get("profitFactor"),
             a.get("winRate"), a["finalEquity"]))
    print("  C 정제필터       : trades=%d CAGR=%s MDD=%s PF=%s winRate=%s finalEquity=%s (blocked=%d)"
          % (variant_c["closedPositionCount"], c["cagr"], c["mdd"], c.get("profitFactor"),
             c.get("winRate"), c["finalEquity"], variant_c["blockedEntryCount"]))
    print("\n[참고 - 원본 필터(Risk-Off 전부 차단), findings/5dc-riskoff-runner-validation-2026-08.md]")
    print("  B 원본필터: trades=1476 CAGR=-0.0509 MDD=-0.6155 finalEquity=52,686,529 (blocked=1706)")

    result = {
        "context": "정제 Risk-Off 필터(Risk-Off AND vixState in Low/Mid만 차단) 실제 runner 검증 - "
                   "P1-1(vix-incremental-info-check)의 관측이 실제 가치로 이어지는지 확인",
        "period": "%s ~ %s" % (START, END), "universeMode": universe.mode,
        "variantA_baseline": variant_a, "variantC_riskoffVixRefined": variant_c,
        "originalFilterReference": {
            "source": "findings/5dc-riskoff-runner-validation-2026-08.md (variant B, Risk-Off 전부 차단)",
            "trades": 1476, "cagr": -0.0509, "mdd": -0.6155, "finalEquity": 52686529, "blockedEntryCount": 1706,
        },
    }
    out_dir = os.path.join(REPORTS_DIR, "2026-08-24-5dc-riskoff-vix-refined-runner-validation")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "5dc-riskoff-vix-refined-runner-validation.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": result},
                   f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
