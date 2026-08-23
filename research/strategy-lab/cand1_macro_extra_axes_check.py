#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAND1(PMCRASH_REVERSAL) — 미검증 macro 6축 확장 검증 (2026-08).

배경: cand1_macro_rate_regime_check.py(2026-08)가 usTreasury10y 1축만 검증했다.
market_regime_features.parquet의 아직 안 쓴 6축(usFedFundsRate·usNasdaq·
krKospi·krCpi·krLeadingCyclical·krCoincidentCyclical)에 **완전히 같은 방법론**을
그대로 적용한다 — 새 설계·임계값 결정 없음, 축 확장 반복.

**핵심 한계(먼저 밝힌다)**: 원본과 동일 — CAND1 신호는 분봉 캐시 기반이라
데이터 창이 약 1년뿐이다(2025-08~2026-08). 1년 안의 하위구간 비교지 다년도
교차검증이 아니므로 결과를 PBR급 증거와 동일시하면 안 된다.

방법: `analyze_cand1_regime_conditional.py`의 검증된 함수(`build_signal_trades`·
`next_trading_day_map`·`trade_stats`·`daily_portfolio_series`·`mdd_from_returns`)
를 무변경 재사용하고, entryDate를 market_regime_features.parquet의 `date`
컬럼에 직접(asof-backward) 조인한다(parquet 축은 이미 PIT 시프트 완료, 중복
시프트 없음 — 원본과 동일). 각 축 trailing 126거래일 변화(col - col.shift(126),
threshold >0)로 버킷 비교. 신호·체결·비용(thr=0.02, vthr=1.5, entry=n_open,
exit=n_c0935, cost=20bp) 전부 무변경, trailDays=126 사전고정.

  python cand1_macro_extra_axes_check.py
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REGIME_PARQUET = HERE / "data" / "market-regime" / "market_regime_features.parquet"
OUT_MD = HERE / "findings" / "cand1-macro-extra-axes-2026-08.md"
TRAIL_DAYS = 126  # 원본 조사들과 동일 사전고정(재최적화 없음)

sys.path.insert(0, str(HERE))

from analyze_cand1_regime_conditional import (  # noqa: E402
    build_signal_trades, daily_portfolio_series, mdd_from_returns,
    next_trading_day_map, trade_stats,
)

EXTRA_AXES = [
    ("usFedFundsRate", "미국 연방기금금리"),
    ("usNasdaq", "나스닥 지수"),
    ("krKospi", "KOSPI 지수"),
    ("krCpi", "한국 CPI"),
    ("krLeadingCyclical", "한국 선행순환지수"),
    ("krCoincidentCyclical", "한국 일반순환지수"),
]


def load_extra_axes():
    cols = ["date"] + [c for c, _ in EXTRA_AXES]
    df = pd.read_parquet(REGIME_PARQUET)[cols].copy()
    df = df.sort_values("date").reset_index(drop=True)
    for col, _ in EXTRA_AXES:
        df[col + "Chg6m"] = df[col] - df[col].shift(TRAIL_DAYS)
    df["date"] = pd.to_datetime(df["date"])
    return df


def attach_entry_axes(trades, nxt_map, axes_df):
    trades = trades.copy()
    trades["entryDate"] = trades["signalDate"].map(nxt_map)
    trades = trades.dropna(subset=["entryDate"]).reset_index(drop=True)
    left = trades.copy()
    left["entryDate_dt"] = pd.to_datetime(left["entryDate"])
    chg_cols = ["date"] + [c + "Chg6m" for c, _ in EXTRA_AXES]
    merged = pd.merge_asof(
        left.sort_values("entryDate_dt"), axes_df[chg_cols],
        left_on="entryDate_dt", right_on="date", direction="backward")
    return merged.drop(columns=["entryDate_dt", "date"])


def bucket_and_report(trades, chg_col):
    sub = trades.dropna(subset=[chg_col]).copy()
    up = sub[sub[chg_col] > 0]
    not_up = sub[sub[chg_col] <= 0]
    out = {}
    for name, s in (("up", up), ("not_up", not_up)):
        if len(s) > 0:
            stats = trade_stats(s)
            dpn = daily_portfolio_series(s, "pnlNet")
            stats["netMeanBp"] = round(float(dpn.mean()) * 10000, 2)
            stats["mddPct"] = mdd_from_returns(dpn)
        else:
            stats = {}
        out[name] = stats
    return out, sub


def main():
    t0 = time.time()
    from run_strategy_validation import load_frame
    print("load_frame() 로드 중...")
    f, p, _g = load_frame()
    dates = sorted(f["date"].unique())
    print("가용 세션: %d, 범위 %s~%s (%.0fs)" % (len(dates), dates[0], dates[-1], time.time() - t0))

    nxt_map = next_trading_day_map()
    axes_df = load_extra_axes()

    trades = build_signal_trades(f)
    trades = attach_entry_axes(trades, nxt_map, axes_df)

    full_stats = trade_stats(trades)
    dpn_full = daily_portfolio_series(trades, "pnlNet")
    full_stats["netMeanBp"] = round(float(dpn_full.mean()) * 10000, 2)
    full_stats["mddPct"] = mdd_from_returns(dpn_full)
    print("\n전체(baseline): 거래수=%d net(bp)=%.2f 승률=%.1f%% PF=%.2f MDD=%.2f%%"
          % (full_stats["trades"], full_stats["netMeanBp"], full_stats["winRate"] * 100,
             full_stats["profitFactor"], full_stats["mddPct"]))

    results = {}
    for col, label in EXTRA_AXES:
        chg_col = col + "Chg6m"
        n_no_axis = int(trades[chg_col].isna().sum())
        bucketed, sub = bucket_and_report(trades, chg_col)
        date_ranges = {}
        for name, mask in (("up", sub[chg_col] > 0), ("not_up", sub[chg_col] <= 0)):
            g = sub[mask]
            date_ranges[name] = [g["entryDate"].min(), g["entryDate"].max()] if len(g) else None
        results[chg_col] = {"label": label, "tradesNoAxis": n_no_axis,
                            "buckets": bucketed, "dateRanges": date_ranges}
        print("\n[%s - trailing %d거래일 변화 >0 여부]" % (label, TRAIL_DAYS))
        print("  axis 매칭 안 된 거래수:", n_no_axis, "/", len(trades))
        for name, lab in (("up", "상승(up)"), ("not_up", "하락/정체(not)")):
            s = bucketed[name]
            print("  %-14s 거래수=%d net(bp)=%s 승률=%s PF=%s MDD=%s 기간=%s"
                  % (lab, s.get("trades", 0), s.get("netMeanBp"), s.get("winRate"),
                     s.get("profitFactor"), s.get("mddPct"), date_ranges[name]))

    lines = []
    lines.append("# CAND1 — 미검증 macro 6축 확장 검증 (2026-08)\n\n")
    lines.append(
        "cand1_macro_rate_regime_check.py(미국 10년물 1축)에 이어, 아직 안 쓴 "
        "macro 6축(연방기금금리·나스닥·KOSPI·한국 CPI·선행순환지수·일반순환지수)에 "
        "**완전히 같은 방법론**을 적용했다. 신호·체결·비용 전부 무변경(thr=%.2f·"
        "vthr=%.1f·entry=%s·exit=%s·cost=%dbp), trailDays=%d 사전고정.\n\n"
        "**한계를 먼저 밝힌다**: CAND1 데이터 창은 %s~%s(약 1년)뿐이다 — 1년 안의 "
        "하위구간 비교지 다년도 교차검증이 아니다. 이 결과를 PBR급 증거와 동일시하면 안 된다.\n\n---\n\n"
        % (0.02, 1.5, "n_open", "n_c0935", 20, TRAIL_DAYS, dates[0], dates[-1])
    )
    lines.append("## 결과\n\n")
    lines.append("| 구간 | 거래수 | 승률 | PF | net(bp) | MDD(%) | 기간 |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    lines.append("| 전체(baseline) | %d | %.1f%% | %.2f | %.2f | %.2f | %s~%s |\n"
                 % (full_stats["trades"], full_stats["winRate"] * 100,
                    full_stats["profitFactor"], full_stats["netMeanBp"],
                    full_stats["mddPct"], dates[0], dates[-1]))
    for col, label in EXTRA_AXES:
        r = results[col + "Chg6m"]
        b = r["buckets"]
        for name, lab in (("up", "%s 상승" % label), ("not_up", "%s 하락/정체" % label)):
            s = b[name]
            dr = r["dateRanges"][name]
            dr_str = ("%s~%s" % (dr[0], dr[1])) if dr else "—"
            if s.get("trades", 0) > 0:
                lines.append("| %s | %d | %.1f%% | %.2f | %.2f | %.2f | %s |\n"
                             % (lab, s["trades"], s["winRate"] * 100, s["profitFactor"],
                                s["netMeanBp"], s["mddPct"], dr_str))
            else:
                lines.append("| %s | 0 | — | — | — | — | %s |\n" % (lab, dr_str))
    lines.append("\n(axis 매칭 실패 거래수는 각 축 trailing 126거래일 창 미확보분)")
    lines.append("\n\n---\n\n## 검증 가능한 근거 목록\n\n")
    lines.append(
        "- `cand1_macro_extra_axes_check.py` — 재실행하면 동일 결과\n"
        "- `analyze_cand1_regime_conditional.py` — `build_signal_trades`·"
        "`trade_stats`·`daily_portfolio_series`·`mdd_from_returns` 무변경 재사용\n"
        "- `cand1_macro_rate_regime_check.py` — 동일 방법론 원출처(usTreasury10y 축)\n"
        "- `data/market-regime/market_regime_features.parquet` — 6축 원천\n"
    )
    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("\nwrote", OUT_MD)

    out_dir = HERE / "reports" / "2026-08-24-cand1-macro-extra-axes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "cand1-macro-extra-axes.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "CAND1 미검증 macro 6축 확장 검증 - "
                       "cand1_macro_rate_regime_check.py와 동일 방법론의 축 확장 반복",
            "trailDays": TRAIL_DAYS,
            "period": [dates[0], dates[-1]],
            "fullStats": full_stats,
            "results": results,
        }, fh, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
