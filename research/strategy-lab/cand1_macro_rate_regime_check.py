#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAND1(PMCRASH_REVERSAL) — 미국 10년물 금리 hiking regime 조건부 확인 (2026-08).

배경: PBR 조사(pbr_macro_rate_regime_check.py, 2026-08-23)에서 미국 10년물
금리의 trailing 6개월(126거래일) 변화가 2022년 하나로만 설명되지 않는 실제
regime 축임을 확인했다. 사용자 지시로 같은 축을 CAND1에도 적용한다.

**핵심 한계(먼저 밝힌다)**: CAND1 신호는 분봉 캐시 기반이라 데이터 창이
2025-08-08~2026-08-21(약 1년)뿐이다(analyze_cand1_regime_conditional.py와
동일 제약, findings/regime-conditional-synthesis-2026-08.md §0에 이미 기록됨).
PBR처럼 "2022년을 빼고 나머지 9년으로 재검증"하는 게 원리적으로 불가능하다 —
이 조사는 **1년 안의 하위구간 비교**이지 PBR급의 다년도 교차검증이 아니다.
결과를 그 수준으로 해석하면 안 된다.

방법: `analyze_cand1_regime_conditional.py`의 검증된 함수(`build_signal_trades`·
`next_trading_day_map`·`trade_stats`·`daily_portfolio_series`·`mdd_from_returns`)
를 **무변경 재사용**한다. 기존 스크립트는 진입일의 `usableFromDate`를
regime_labels.parquet에서 조인했지만, market_regime_features.parquet의
`usTreasury10y` 컬럼은 asof_join_kr()이 이미 "관측일 < D" 규칙으로 한 번
시프트해뒀으므로 **entryDate를 그 parquet의 `date` 컬럼에 직접(asof-backward)
조인**하면 같은 PIT 안전성을 얻는다(중복 시프트 없음 — pbr_macro_rate_regime_
check.py와 동일 방식).

신호·체결·비용(thr=0.02, vthr=1.5, entry=n_open, exit=n_c0935, cost=20bp)
전부 무변경. trailDays=126은 PBR 조사와 동일 사전고정값(재최적화 없음).

  python cand1_macro_rate_regime_check.py
"""
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
REGIME_PARQUET = HERE / "data" / "market-regime" / "market_regime_features.parquet"
OUT_MD = HERE / "findings" / "cand1-macro-rate-regime-check-2026-08.md"
TRAIL_DAYS = 126  # PBR 조사와 동일 사전고정(재최적화 없음)

sys.path.insert(0, str(HERE))

from analyze_cand1_regime_conditional import (  # noqa: E402
    build_signal_trades, daily_portfolio_series, mdd_from_returns,
    next_trading_day_map, trade_stats,
)


def load_rate_axis():
    df = pd.read_parquet(REGIME_PARQUET)[["date", "usTreasury10y"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    df["usTreasury10yChg6m"] = df["usTreasury10y"] - df["usTreasury10y"].shift(TRAIL_DAYS)
    df["date"] = pd.to_datetime(df["date"])
    return df


def attach_entry_rate_axis(trades, nxt_map, rate_df):
    trades = trades.copy()
    trades["entryDate"] = trades["signalDate"].map(nxt_map)
    trades = trades.dropna(subset=["entryDate"]).reset_index(drop=True)
    left = trades.copy()
    left["entryDate_dt"] = pd.to_datetime(left["entryDate"])
    merged = pd.merge_asof(
        left.sort_values("entryDate_dt"), rate_df[["date", "usTreasury10yChg6m"]],
        left_on="entryDate_dt", right_on="date", direction="backward")
    return merged.drop(columns=["entryDate_dt", "date"])


def bucket_and_report(trades, label_col="hiking"):
    trades = trades.dropna(subset=["usTreasury10yChg6m"]).copy()
    trades[label_col] = trades["usTreasury10yChg6m"] > 0
    out = {}
    for name, sub in (("hiking", trades[trades[label_col]]), ("not_hiking", trades[~trades[label_col]])):
        s = trade_stats(sub)
        if len(sub) > 0:
            dpn = daily_portfolio_series(sub, "pnlNet")
            s["netMeanBp"] = round(float(dpn.mean()) * 10000, 2)
            s["mddPct"] = mdd_from_returns(dpn)
        out[name] = s
    return out, trades


def main():
    from run_strategy_validation import load_frame
    print("load_frame() 로드 중...")
    f, p, _g = load_frame()
    dates = sorted(f["date"].unique())
    print("가용 세션: %d, 범위 %s~%s" % (len(dates), dates[0], dates[-1]))

    nxt_map = next_trading_day_map()
    rate_df = load_rate_axis()

    trades = build_signal_trades(f)
    trades = attach_entry_rate_axis(trades, nxt_map, rate_df)
    n_no_axis = int(trades["usTreasury10yChg6m"].isna().sum())

    full_stats = trade_stats(trades)
    dpn_full = daily_portfolio_series(trades, "pnlNet")
    full_stats["netMeanBp"] = round(float(dpn_full.mean()) * 10000, 2)
    full_stats["mddPct"] = mdd_from_returns(dpn_full)

    bucketed, trades_w = bucket_and_report(trades)

    # 진입일 기준 미국10년물 hiking/not-hiking 각각의 날짜 범위(1년 창 안의
    # 하위구간이라는 걸 독자가 바로 알 수 있게)
    date_ranges = {}
    for name, sub in (("hiking", trades_w[trades_w["hiking"]]),
                       ("not_hiking", trades_w[~trades_w["hiking"]])):
        if len(sub):
            date_ranges[name] = [sub["entryDate"].min(), sub["entryDate"].max()]
        else:
            date_ranges[name] = None

    print("\n전체(baseline): 거래수=%d net(bp)=%.2f 승률=%.1f%% PF=%.2f MDD=%.2f%%"
          % (full_stats["trades"], full_stats["netMeanBp"], full_stats["winRate"] * 100,
             full_stats["profitFactor"], full_stats["mddPct"]))
    for name in ("hiking", "not_hiking"):
        s = bucketed[name]
        print("%-12s 거래수=%d net(bp)=%s 승률=%s PF=%s MDD=%s 기간=%s"
              % (name, s.get("trades", 0), s.get("netMeanBp"), s.get("winRate"),
                 s.get("profitFactor"), s.get("mddPct"), date_ranges[name]))
    print("axis 매칭 안 된 거래수:", n_no_axis, "/", len(trades))

    lines = []
    lines.append("# CAND1 — 미국 10년물 금리 hiking regime 조건부 확인 (2026-08)\n\n")
    lines.append(
        "PBR 조사(pbr_macro_rate_regime_check.py)에서 2022년을 빼도 살아남은 "
        "유일한 축(미국 10년물 trailing 6개월 변화)을 CAND1에도 적용했다. "
        "신호·체결·비용 전부 무변경(thr=%.2f·vthr=%.1f·entry=%s·exit=%s·cost=%dbp), "
        "trailDays=%d는 PBR 조사와 동일 사전고정값.\n\n"
        "**한계를 먼저 밝힌다**: CAND1 데이터 창은 %s~%s(약 1년)뿐이다 — PBR처럼 "
        "여러 해를 넘나드는 교차검증이 아니라 **1년 안의 하위구간 비교**다. "
        "이 결과를 PBR급의 다년도 증거와 동일시하면 안 된다.\n\n---\n\n"
        % (0.02, 1.5, "n_open", "n_c0935", 20, TRAIL_DAYS, dates[0], dates[-1])
    )
    lines.append("## 결과\n\n")
    lines.append("| 구간 | 거래수 | 승률 | PF | net(bp) | MDD(%) | 기간 |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    lines.append("| 전체(baseline) | %d | %.1f%% | %.2f | %.2f | %.2f | %s~%s |\n"
                  % (full_stats["trades"], full_stats["winRate"] * 100,
                     full_stats["profitFactor"], full_stats["netMeanBp"],
                     full_stats["mddPct"], dates[0], dates[-1]))
    for name, label in (("hiking", "미국10Y 상승(hiking)"), ("not_hiking", "미국10Y 하락/정체")):
        s = bucketed[name]
        dr = date_ranges[name]
        dr_str = ("%s~%s" % (dr[0], dr[1])) if dr else "—"
        if s.get("trades", 0) > 0:
            lines.append("| %s | %d | %.1f%% | %.2f | %.2f | %.2f | %s |\n"
                          % (label, s["trades"], s["winRate"] * 100, s["profitFactor"],
                             s["netMeanBp"], s["mddPct"], dr_str))
        else:
            lines.append("| %s | 0 | — | — | — | — | %s |\n" % (label, dr_str))
    lines.append("\naxis 매칭 안 된 거래수: %d / %d\n\n" % (n_no_axis, len(trades)))
    lines.append("---\n\n## 검증 가능한 근거 목록\n\n")
    lines.append(
        "- `cand1_macro_rate_regime_check.py` — 재실행하면 동일 결과\n"
        "- `analyze_cand1_regime_conditional.py` — `build_signal_trades`·"
        "`trade_stats`·`daily_portfolio_series`·`mdd_from_returns` 무변경 재사용\n"
        "- `pbr_macro_rate_regime_check.py` — 동일 축·동일 trailDays(126) 원출처\n"
        "- `data/market-regime/market_regime_features.parquet` — usTreasury10y\n"
    )
    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("\nwrote", OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
