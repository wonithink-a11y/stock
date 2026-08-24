#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P0-2: TREND-BREAKOUT-v1 Risk-Off 신규진입 회피 - 실제 runner 검증.

`5dc_riskoff_runner_validation.py`(P0-1 후속, 5DC-v1A-P 대상)를
TREND-BREAKOUT-v1으로 일반화한 복제본이다. 5DC에서 확인된 "Risk-Off 국면
신규 진입 차단" 필터의 실제 Portfolio 스케줄러 효과(슬롯/현금 재배정 포함)가
다른 전략에도 그대로 통하는지 본다 - 새로운 설계·임계값 결정 없음.

## 원본 대응 관계 (5dc_riskoff_runner_validation.py -> 이 파일)

- 바꾼 것: `load_strategy("5dc_v1a_p", ...)` -> `load_strategy("trend_breakout_v1",
  ...)` 하나뿐. print/JSON 라벨만 TREND-BREAKOUT-v1로 갱신. 오프라인
  counterfactual 대조는 TREND-BREAKOUT-v1에 사전 offline 실험이 없으므로 생략.
- 그대로 재사용: START/END, FinalizedA2bProvider, load_merged_bars_finalized,
  load_pit_regime_lookup(Risk-Off PIT 라벨 규칙), 
  schedule_portfolio_with_riskoff_filter(필터 적용 시점), run_variant(측정 지표)
  - 전부 5DC와 동일. 재최적화·재설계 없음.
- `run_5dc_v1a_p_merged.py`의 `run_5dc_pipeline()`은 이름과 달리 범용 함수라
  (rule.PARAMS/compute_features/generate_signals/risk_spec_for만 사용)
  trend_breakout_v1 rule을 넣으면 그대로 동작한다 -
  strategies/trend_breakout_v1/policy.json의 portfolio 블록이 5dc_v1a_p와
  동일 구조(maxPositions=10, equalWeight=true, tieBreak=ticker_ascending).
- 원본 `5dc_riskoff_runner_validation.py`와 `run_5dc_v1a_p_merged.py`는 무수정.

  python trend_breakout_riskoff_runner_validation.py
"""
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.priceProvider import PriceProvider  # noqa: E402
from engine.data.universeProvider import UniverseProvider  # noqa: E402
from engine.metrics.metrics import trade_stats  # noqa: E402
from engine.portfolio.portfolio import Portfolio, PortfolioConfig  # noqa: E402
from engine.runner import load_strategy  # noqa: E402
from run_5dc_v1a_p_merged import (  # noqa: E402
    _drop_suspension_rows, realized_pnl_metrics, run_5dc_pipeline,
    trades_from_portfolio, yearly_breakdown,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A2B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2b")
MRD = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "market-regime")
START, END = "2014-05-13", "2026-08-03"  # run_5dc_v1a_p_merged.py의 main()과 동일 기간


class FinalizedA2bProvider(PriceProvider):
    """정식 finalize된 data/backfill/price/a2b/{year}.jsonl.gz를 읽는
    대체 provider - 원본 run_5dc_v1a_p_merged.py의 A2bProvider(임시 CI shard용)
    와 같은 인터페이스, 데이터 소스만 정식본으로 교체."""

    def __init__(self, a2b_dir, start, end):
        diag = json.load(open(os.path.join(a2b_dir, "_diagnostics.json"), encoding="utf-8"))
        self.excluded = {q["ticker"] for q in diag.get("qualityExcluded", [])}
        self._diag_raw = diag
        self._bars = {}
        self._start, self._end = start, end
        self._a2b_dir = a2b_dir

    @property
    def manifest_hash(self):
        return "a2b-finalized-2026-08-17"

    def coverage(self, ticker):
        df = self._bars.get(ticker)
        if df is None or df.empty:
            return None
        return (df.index[0].strftime("%Y-%m-%d"), df.index[-1].strftime("%Y-%m-%d"))

    def load(self, tickers, start, end, universe_hash="none"):
        want = set(tickers) - self.excluded
        buffers = {t: [] for t in want}
        years = sorted(int(f[:-9]) for f in os.listdir(self._a2b_dir)
                       if f.endswith(".jsonl.gz") and f[:-9].isdigit())
        for y in years:
            if y < int(start[:4]) or y > int(end[:4]):
                continue
            path = os.path.join(self._a2b_dir, "%d.jsonl.gz" % y)
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    ticker = row["ticker"]
                    if ticker not in buffers:
                        continue
                    date = row["date"]
                    if date < start or date > end:
                        continue
                    buffers[ticker].append(row)
        result = {}
        for t, rows in buffers.items():
            if not rows:
                continue
            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").set_index("date")
            for col in ("open", "high", "low", "close"):
                df[col] = df[col].astype("float32")
            df["volume"] = df["volume"].astype("int64")
            result[t] = df[["open", "high", "low", "close", "volume"]]
        self._bars = result
        return result


def load_merged_bars_finalized(repo_root, universe, start, end):
    a1a_tickers = {e.ticker for e in universe.entries if e.source == "A1A"}
    a1b_tickers = {e.ticker for e in universe.entries if e.source == "A1B"}

    a2a = A2aProvider(repo_root=repo_root, use_cache=True)
    bars_a1a = a2a.load(a1a_tickers, start, end, universe_hash=universe.universe_hash)

    a2b = FinalizedA2bProvider(A2B_DIR, start, end)
    bars_a1b = a2b.load(a1b_tickers, start, end, universe_hash=universe.universe_hash)
    merged = dict(bars_a1a)
    merged.update(bars_a1b)

    class _MergedProvider(PriceProvider):
        @property
        def manifest_hash(self):
            return "%s+%s" % (a2a.manifest_hash, a2b.manifest_hash)

        def coverage(self, ticker):
            if ticker in bars_a1a:
                return a2a.coverage(ticker)
            if ticker in bars_a1b:
                return a2b.coverage(ticker)
            return None

        def load(self, tickers, start, end, universe_hash="none"):
            return {t: merged[t] for t in set(tickers) if t in merged}

    return merged, _MergedProvider(), len(a2b.excluded)


# ---- Risk-Off PIT 라벨 결합 (riskoff_filter_validation.py와 완전히 동일 규칙) ----

def load_pit_regime_lookup():
    rl = pd.read_parquet(os.path.join(MRD, "regime_labels.parquet"))
    rl["date"] = rl["date"].astype(str)
    rl["usable"] = rl["usableFromDate"].astype(str)
    lab = rl[["date", "usable", "regime"]].sort_values("usable").reset_index(drop=True)
    usable_arr = lab["usable"].to_numpy()
    reg_arr = lab["regime"].to_numpy()

    def _fn(entry_date):
        j = np.searchsorted(usable_arr, entry_date, side="right") - 1
        if j < 0:
            return "PRE-LABEL"
        return str(reg_arr[j])

    return _fn


# ---- 실제 스케줄러 - Risk-Off 신규진입만 차단(청산 불간섭), 그 외 로직은
# run_5dc_v1a_p_merged.py::_schedule_portfolio()와 완전히 동일(원본 무변경,
# 이 함수만 복제+필터 한 줄) ----

def schedule_portfolio_with_riskoff_filter(resolved, portfolio, portfolio_cfg, regime_of, apply_filter):
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
            if apply_filter and regime_of(order.order_date) == "Risk-Off":
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


def run_variant(repo_root, rule, universe, bars_by_ticker, price_provider, regime_of, apply_filter, label):
    t0 = time.time()
    params = rule.PARAMS
    # run_5dc_pipeline은 자체 스케줄러를 쓰므로, resolved 생성까지만 재사용하고
    # 스케줄링은 우리 함수로 대체한다 - resolved 리스트(신호->체결) 자체는
    # run_5dc_pipeline과 완전히 동일 코드로 만든다(재사용).
    base = run_5dc_pipeline(repo_root, START, END, rule, universe, bars_by_ticker, price_provider)
    resolved = base["resolved"]

    from engine.data.calendar import TradingCalendar
    calendar = TradingCalendar(repo_root=repo_root)
    portfolio_cfg = PortfolioConfig(
        initial_capital=params["portfolio"]["initialCapital"],
        max_positions=params["portfolio"]["maxPositions"],
        equal_weight=params["portfolio"]["equalWeight"],
        fractional_shares=params["portfolio"]["fractionalShares"],
        tie_break=params["portfolio"]["tieBreak"],
    )
    portfolio = Portfolio(portfolio_cfg)
    max_open, blocked = schedule_portfolio_with_riskoff_filter(
        resolved, portfolio, portfolio_cfg, regime_of, apply_filter)

    trades = trades_from_portfolio(portfolio)
    t_stats = trade_stats(trades)
    realized = realized_pnl_metrics(portfolio, START, END)
    print("  [%s] %d resolved-eligible, %d closed, %d open at end, blocked_entries=%d (%.0fs)"
          % (label, len(resolved), len(trades), len(portfolio.open_positions), blocked, time.time() - t0))
    return {
        "label": label, "resolvedEligibleCount": len(resolved),
        "closedPositionCount": len(trades), "openPositionCountAtEnd": len(portfolio.open_positions),
        "maxSimultaneousPositionsObserved": max_open, "blockedEntryCount": blocked,
        "resultTable": {**{k: v for k, v in t_stats.items()},
                        "finalEquity": realized["finalEquity"], "totalReturn": realized["totalReturn"],
                        "cagr": realized["cagr"], "mdd": realized["mdd"], "sharpe": realized["sharpe"],
                        "calmar": realized["calmar"]},
        "yearlyBreakdown": yearly_breakdown(trades),
        "trades": trades,
    }


def main():
    t0 = time.time()
    rule = load_strategy("trend_breakout_v1", REPO_ROOT)
    universe = UniverseProvider(repo_root=REPO_ROOT, include_delisted=True)
    print("universe: %s (%d entries)" % (universe.mode, len(universe.tickers)))

    bars_raw, provider, n_excluded = load_merged_bars_finalized(REPO_ROOT, universe, START, END)
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print("bars loaded: %d tickers (a2b qualityExcluded=%d) (%.0fs)"
          % (len(bars_by_ticker), n_excluded, time.time() - t0))

    regime_of = load_pit_regime_lookup()

    print("\n=== A. baseline (필터 없음) ===")
    variant_a = run_variant(REPO_ROOT, rule, universe, bars_by_ticker, provider, regime_of,
                             apply_filter=False, label="A_baseline")
    print("=== B. Risk-Off 신규진입 차단 (실제 runner, 슬롯/현금 재배정 포함) ===")
    variant_b = run_variant(REPO_ROOT, rule, universe, bars_by_ticker, provider, regime_of,
                             apply_filter=True, label="B_riskoff_skip")

    a, b = variant_a["resultTable"], variant_b["resultTable"]
    print("\n[결과]")
    print("  A baseline : trades=%d CAGR=%s MDD=%s PF=%s winRate=%s finalEquity=%s"
          % (variant_a["closedPositionCount"], a["cagr"], a["mdd"], a.get("profitFactor"),
             a.get("winRate"), a["finalEquity"]))
    print("  B filtered : trades=%d CAGR=%s MDD=%s PF=%s winRate=%s finalEquity=%s (blocked=%d)"
          % (variant_b["closedPositionCount"], b["cagr"], b["mdd"], b.get("profitFactor"),
             b.get("winRate"), b["finalEquity"], variant_b["blockedEntryCount"]))

    out = {
        "context": "P0-2 - TREND-BREAKOUT-v1 Risk-Off 필터 실제 runner(Portfolio 스케줄러, "
                   "슬롯/현금 재배정 포함) 검증. 5dc_riskoff_runner_validation.py(P0-1 후속, "
                   "5DC-v1A-P)의 일반화 복제본 - 전략 ID만 trend_breakout_v1으로 교체, "
                   "Risk-Off PIT 라벨 규칙/필터 적용 시점/측정 지표는 5DC와 동일. "
                   "run_5dc_v1a_p_merged.py의 run_5dc_pipeline() 무변경 재사용, "
                   "A2b는 정식 finalize된 data/backfill/price/a2b 사용.",
        "period": "%s ~ %s" % (START, END), "universeMode": universe.mode,
        "strategyId": "trend_breakout_v1",
        "a2bQualityExcludedCount": n_excluded,
        "variantA_baseline": variant_a, "variantB_riskoffSkip": variant_b,
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-24-trendbreakout-riskoff-runner-validation")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "trendbreakout-riskoff-runner-validation.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": out},
                   f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
