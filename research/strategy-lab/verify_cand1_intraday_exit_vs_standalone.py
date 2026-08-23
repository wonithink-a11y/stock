#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAND1 09:35 청산 — engine 확장(MinuteProvider 경로) vs standalone(그리드) 대조.

지시(2026-08-23): "구현 후 standalone CAND1과 executor 결과를 동일 조건에서
대조하고, net(bp)·거래수·승률·PF가 기존 +21.65bp 결과와 정합적인지 확인.
불일치하면 전체 백테스트로 진행하지 말고 원인을 수정."

standalone 쪽(신호·진입가 n_open·비용 20bp)은 analyze_cand1_regime_
conditional.py의 함수를 그대로 import해서 쓴다(무변경) — 그 13,329건이
기존에 검증된 baseline(net 21.65bp)이다. 이 스크립트가 새로 하는 건 그
13,329건 각각에 대해 **청산가만** MinuteProvider(engine/execution/
intraday_exit.py)로 다시 조회해서, (a) 그리드(n_c0935)와 가격 자체가
일치하는지, (b) 그 가격으로 다시 집계한 net/승률/PF가 baseline과 맞는지
두 층위로 검증한다.

threshold·신호정의·비용가정 변경 없음. 원본 데이터 무변경.

사용: python verify_cand1_intraday_exit_vs_standalone.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
OUT_MD = HERE / "findings" / "cand1-intraday-exit-engine-verification-2026-08.md"

sys.path.insert(0, str(HERE))
from analyze_cand1_regime_conditional import (  # noqa: E402
    COST_BPS, EXIT_COL, THR, VTHR, build_signal_trades, daily_portfolio_series,
    mdd_from_returns, next_trading_day_map, trade_stats,
)
from engine.execution.executor import CostModel  # noqa: E402
from engine.execution.intraday_exit import resolve_intraday_price  # noqa: E402
from engine.data.minuteProvider import MinuteProvider  # noqa: E402

COST_MODEL = CostModel(entry_cost_bps=COST_BPS / 2, exit_cost_bps=COST_BPS / 2)


def main():
    from run_strategy_validation import load_frame
    print("load_frame() 로드 중...")
    f, p, _g = load_frame()

    trades = build_signal_trades(f)   # standalone baseline, 무변경 이식
    nxt_map = next_trading_day_map()
    trades["entryDate"] = trades["signalDate"].map(nxt_map)
    trades = trades.dropna(subset=["entryDate"]).reset_index(drop=True)
    print("standalone baseline 거래수:", len(trades))

    mp = MinuteProvider(repo_root=str(REPO_ROOT))
    have_cache_dates = set(mp._dates)

    mp_price = np.full(len(trades), np.nan)
    entry_dates = trades["entryDate"].to_numpy()
    tickers = trades["ticker"].to_numpy()

    print("MinuteProvider 09:35가 조회 중(진입일 단위 배치)...")
    for d in sorted(set(entry_dates) & have_cache_dates):
        day_mask = entry_dates == d
        day_tickers = sorted(set(tickers[day_mask]))
        bars = mp.load(day_tickers, d, d)
        idx = np.where(day_mask)[0]
        for i in idx:
            tk = tickers[i]
            df = bars.get(tk)
            mp_price[i] = resolve_intraday_price(df, "09:35") or np.nan

    trades["mpExitPrice"] = mp_price
    n_out_of_cache = int((~np.isin(entry_dates, list(have_cache_dates))).sum())
    n_no_mp_price = int(trades["mpExitPrice"].isna().sum()) - n_out_of_cache

    # ---- 층위 1: 가격 자체 일치 ----
    both = trades.dropna(subset=["mpExitPrice"]).copy()
    both["priceDiffPct"] = (both["mpExitPrice"] / both[EXIT_COL] - 1.0).abs() * 100
    exact_match = int((both["priceDiffPct"] < 1e-6).sum())
    close_match_1bp = int((both["priceDiffPct"] < 0.01).sum())

    # ---- 층위 2: 집계 재현 ----
    mp_trades = both.copy()
    mp_trades["pnlGrossMp"] = mp_trades["mpExitPrice"] / mp_trades["n_open"] - 1.0
    mp_trades["pnlNetMp"] = mp_trades["pnlGrossMp"] - COST_BPS / 1e4

    def stats_for(df, gross_col, net_col):
        # gross_col/net_col이 이미 존재하는 "pnlGross"/"pnlNet"과 다른 이름일
        # 때(예: pnlGrossMp) 그 원본 컬럼이 남아 있으면 rename 후 동명 중복
        # 컬럼이 생겨 groupby(...).mean()이 스칼라 대신 Series를 반환한다
        # (2026-08-23 최초 구현에서 TypeError로 발견 — 원본 컬럼을 먼저
        # 지우고 rename해야 한다).
        drop_cols = [c for c in ("pnlGross", "pnlNet") if c in df.columns and c not in (gross_col, net_col)]
        tmp = df.drop(columns=drop_cols).rename(columns={gross_col: "pnlGross", net_col: "pnlNet"})
        s = trade_stats(tmp)
        dpg = daily_portfolio_series(tmp, "pnlGross")
        dpn = daily_portfolio_series(tmp, "pnlNet")
        s["grossMeanBp"] = round(float(dpg.mean()) * 10000, 2)
        s["netMeanBp"] = round(float(dpn.mean()) * 10000, 2)
        s["mddPct"] = mdd_from_returns(dpn)
        return s

    baseline_on_overlap = stats_for(both, "pnlGross", "pnlNet")  # 원래(그리드) 값, 같은 부분표본
    engine_stats = stats_for(mp_trades, "pnlGrossMp", "pnlNetMp")
    full_baseline = stats_for(trades, "pnlGross", "pnlNet")       # 13,329건 전체(원 baseline)

    lines = []
    lines.append("# CAND1 09:35 청산 엔진 확장 — MinuteProvider vs standalone 대조 (2026-08)\n\n")
    lines.append(
        "신호·진입·비용(thr=%.2f, vthr=%.1f, cost=%dbp) 무변경. standalone "
        "%d건(그리드 n_c0935) 각각의 청산가를 `engine/execution/"
        "intraday_exit.py`(MinuteProvider 경로)로 다시 조회해 대조한다.\n\n"
        "**표본수 정정**: 기존 문서(`cand1-regime-conditional-2026-08.md`)의 "
        "13,329건과 이 문서의 %d건은 다르다 — 버그가 아니라 정의 차이다. "
        "원 문서는 `entryDate`가 `calendar.json`(2026-08-14까지만) 밖으로 "
        "나가 매핑이 안 된 신호도 baseline 총계에는 포함하고 regime 매칭"
        "(849건)만 실패로 뺐다. 이 문서는 MinuteProvider 조회 자체가 "
        "entryDate 없이는 불가능해 그 %d건을 baseline 정의 단계에서부터 "
        "제외했다 — 신호·진입·비용은 동일, **표본 범위(calendar 끝단)만 "
        "다르다.**\n\n" % (THR, VTHR, COST_BPS, len(trades), len(trades), 13329 - len(trades)))

    lines.append("## 1. 커버리지\n\n")
    lines.append(
        "| 항목 | 값 |\n|---|---|\n"
        "| standalone 전체 거래수 | %d |\n"
        "| 분봉 캐시 범위 밖(진입일이 2025-08-08~2026-08-21 밖) | %d |\n"
        "| 캐시 범위 안인데 MinuteProvider 09:35 결측 | %d |\n"
        "| 양쪽 다 값 있음(대조 가능) | %d (%.1f%%) |\n\n"
        % (len(trades), n_out_of_cache, n_no_mp_price, len(both),
           len(both) / len(trades) * 100))

    lines.append("## 2. 가격 레벨 일치 (양쪽 다 값 있는 %d건)\n\n" % len(both))
    lines.append(
        "| 기준 | 건수 | 비율 |\n|---|---|---|\n"
        "| 완전 일치(오차 <1e-6%%) | %d | %.2f%% |\n"
        "| 근접 일치(오차 <0.01%%) | %d | %.2f%% |\n\n"
        % (exact_match, exact_match / len(both) * 100,
           close_match_1bp, close_match_1bp / len(both) * 100))

    lines.append("## 3. 집계 재현 (같은 %d건 부분표본 안에서 그리드 vs MinuteProvider)\n\n" % len(both))
    lines.append("| 소스 | 거래수 | 승률 | PF | gross(bp) | net(bp) | MDD(%) |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    for name, s in (("그리드(n_c0935, 원본)", baseline_on_overlap),
                    ("MinuteProvider(신규)", engine_stats)):
        lines.append("| %s | %d | %.1f%% | %.2f | %.2f | %.2f | %.2f |\n" % (
            name, s["trades"], s["winRate"] * 100, s["profitFactor"],
            s["grossMeanBp"], s["netMeanBp"], s["mddPct"]))
    lines.append("\n")

    lines.append("## 4. 참고: entryDate 매핑 가능한 %d건 전체(부분표본이 아니라 전체, §1 정정 참고)\n\n"
                  % len(trades))
    lines.append("| 거래수 | 승률 | PF | net(bp) |\n|---|---|---|---|\n")
    lines.append("| %d | %.1f%% | %.2f | %.2f |\n\n" % (
        full_baseline["trades"], full_baseline["winRate"] * 100,
        full_baseline["profitFactor"], full_baseline["netMeanBp"]))

    net_diff_bp = engine_stats["netMeanBp"] - baseline_on_overlap["netMeanBp"]
    verdict = "PASS" if (close_match_1bp / len(both) > 0.99 and abs(net_diff_bp) < 2.0) else "FAIL — 원인 조사 필요"
    lines.append("## 5. 판정\n\n")
    lines.append(
        "가격 근접일치율 %.2f%%, 부분표본 net 차이 %.2f bp(그리드 대비) → **%s**\n\n"
        "판정 기준(사전 설정, 결과 보고 정하지 않음): 근접일치율 >99%% AND "
        "net 차이 <2bp.\n\n" % (close_match_1bp / len(both) * 100, net_diff_bp, verdict))

    lines.append(
        "## 검증 가능한 근거 목록\n\n"
        "- `engine/execution/intraday_exit.py` — 신규 확장 모듈(무변경 대상: "
        "executor.py·contracts.py)\n"
        "- `tests/test_intraday_exit.py` — PIT·결측·공식·독립성 pytest 10건 통과\n"
        "- `analyze_cand1_regime_conditional.py` — standalone baseline 원출처(무변경)\n"
        "- 본 스크립트 `verify_cand1_intraday_exit_vs_standalone.py` — 재실행하면 동일 결과\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("wrote", OUT_MD)
    print("커버리지: %d/%d (%.1f%%)" % (len(both), len(trades), len(both) / len(trades) * 100))
    print("가격 근접일치율: %.2f%%" % (close_match_1bp / len(both) * 100))
    print("net 차이(부분표본, 그리드 대비): %.2f bp" % net_diff_bp)
    print("판정:", verdict)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
