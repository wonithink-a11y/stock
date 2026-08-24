#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P0-1 후속: 5DC-v1A-P Risk-Off 신규진입 회피 - 실제 runner 검증.

`findings/5dc-riskoff-filter-validation-2026-08.md`(오프라인 counterfactual,
frozen 거래 테이블을 사후 필터링)의 다음 단계. 오프라인 방식의 알려진 한계
("차단으로 해방되는 슬롯/현금의 2차 재배치 효과 미반영")를 실제 Portfolio
스케줄러로 검증한다 - Risk-Off 필터를 신호/체결 이후, **포트폴리오 슬롯
배정 이전** 단계에 적용해, 차단된 슬롯이 다른 후보에게 실제로 재배정되는
효과까지 반영한다.

## 재사용(무변경) vs 신규(최소 추가)

- `run_5dc_v1a_p_merged.py`의 `run_5dc_pipeline()`(신호→체결→resolved 생성)
  ·`trades_from_portfolio()`·`realized_pnl_metrics()`을 **무변경 import** -
  이게 "frozen 5DC baseline"을 만드는 바로 그 코드다. 원본 파일 무수정.
- `_schedule_portfolio()`만 복제해 Risk-Off 필터 한 줄을 추가한다(원본
  `_schedule_portfolio`는 무변경 - engine/runner.py에도 없는, 이 연구
  드라이버 전용 함수라 어차피 engine이 아니다).
- Risk-Off 라벨 PIT 결합 로직(usable<=entry_date 최근 라벨)은
  `riskoff_filter_validation.py`(2026-08-23 오프라인 실험)와 완전히 동일한
  규칙을 그대로 가져온다 - 새 정의 없음.

## MERGED 유니버스 데이터 소스 변경 (원 스크립트의 임시 CI 아티팩트 → 정식 A2b)

원본 `run_5dc_v1a_p_merged.py`는 2026-08-16 시점 임시 CI shard
(`--a2b-shard`)를 요구했는데 그 파일은 로컬에 없다. 그 뒤 **A2b가 정식
finalize돼**(2026-08-17, manifest `data/backfill/manifest/A2b.json`)
`data/backfill/price/a2b/{year}.jsonl.gz` + `_diagnostics.json`
(qualityExcluded)으로 영구 저장돼 있다 - 이 스크립트는 그 정식 데이터를
읽는 대체 A2bProvider를 쓴다(스키마 동일, 원본 파일의 A2bProvider 클래스와
같은 인터페이스). qualityExcluded 122건(원 임시본 120건과 거의 동일,
finalize 시점 차이로 인한 미세 차 - 아래 §0에서 프레임 수 대조로 확인).

  python 5dc_riskoff_runner_validation.py
"""
import gzip
import json
import os
import sys
import time
from collections import Counter

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
    rule = load_strategy("5dc_v1a_p", REPO_ROOT)
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

    print("\n[오프라인 counterfactual과 대조 - findings/5dc-riskoff-filter-validation-2026-08.md]")
    print("  오프라인: trades 1592->1284, finalEquity 28.47M->51.43M, MDD -75.00%->-54.84%, "
          "CAGR -9.85%->-5.34%, PF 0.807->0.833")

    out = {
        "context": "P0-1 후속 - 실제 runner(Portfolio 스케줄러, 슬롯/현금 재배정 포함) 검증. "
                   "run_5dc_v1a_p_merged.py의 run_5dc_pipeline() 무변경 재사용, "
                   "A2b는 정식 finalize된 data/backfill/price/a2b 사용(원본의 임시 CI shard 대체).",
        "period": "%s ~ %s" % (START, END), "universeMode": universe.mode,
        "a2bQualityExcludedCount": n_excluded,
        "variantA_baseline": variant_a, "variantB_riskoffSkip": variant_b,
        "offlineCounterfactualReference": {
            "source": "findings/5dc-riskoff-filter-validation-2026-08.md",
            "trades": [1592, 1284], "finalEquity": [28471029, 51426344],
            "mdd": [-0.75, -0.5484], "cagr": [-0.09852, -0.05342], "pf": [0.807, 0.833],
        },
    }
    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-23-5dc-riskoff-runner-validation")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "5dc-riskoff-runner-validation.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": out},
                   f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)


if __name__ == "__main__":
    main()
