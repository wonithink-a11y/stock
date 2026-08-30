#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Opening Fade — 미국 10년물 금리 hiking regime 조건부 확인 (2026-08).

배경: PBR 조사(pbr_macro_rate_regime_check.py)에서 2022년을 빼도 살아남은
유일한 축(미국 10년물 trailing 6개월/126거래일 변화)을 CAND1에 이어 Opening
Fade에도 적용한다(사용자 지시).

**한계(먼저 밝힌다)**: Opening Fade도 09:05 진입가가 분봉 캐시 전용이라
데이터 창이 2025-08-08~2026-08-21(약 1년)뿐이다(analyze_opening_fade_regime_
conditional.py와 동일 제약) — CAND1과 같은 이유로 PBR급 다년도 교차검증은
불가능하다. 1년 안의 하위구간 비교로만 해석한다.

방법: `analyze_opening_fade_regime_conditional.py`의 검증된 함수(`load_base`·
`trades_for_horizon`·`group_stats`·`daily_portfolio_series`·`mdd_from_returns`)
를 **무변경 재사용**한다. Opening Fade는 신호일 D 당일 09:05에 진입하므로
(CAND1처럼 T+1이 아니다) 신호일 D를 market_regime_features.parquet의 `date`
컬럼에 직접(asof-backward) 조인한다 — 그 parquet의 usTreasury10y는 이미
"관측일 < D" 규칙으로 시프트돼 있어 D 당일 장 시작 전 정보만 반영한다(원
스크립트의 regime_labels usableFromDate==D 조인과 동일한 PIT 안전성,
중복 시프트 없음).

신호정의·체결규칙·비용(Q1롱+Q5숏, 09:05 진입, RT=30bp) 전부 무변경.
trailDays=126은 PBR·CAND1 조사와 동일 사전고정값(재최적화 없음).

  python opening_fade_macro_rate_regime_check.py
"""
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REGIME_PARQUET = HERE / "data" / "market-regime" / "market_regime_features.parquet"
OUT_MD = HERE / "findings" / "opening-fade-macro-rate-regime-check-2026-08.md"
TRAIL_DAYS = 126  # PBR·CAND1 조사와 동일 사전고정(재최적화 없음)
HORIZONS = ("T+5", "T+10")

sys.path.insert(0, str(HERE))

from analyze_opening_fade_regime_conditional import (  # noqa: E402
    daily_portfolio_series, group_stats, load_base, mdd_from_returns, trades_for_horizon,
)


def load_rate_axis():
    df = pd.read_parquet(REGIME_PARQUET)[["date", "usTreasury10y"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    df["usTreasury10yChg6m"] = df["usTreasury10y"] - df["usTreasury10y"].shift(TRAIL_DAYS)
    df["date_dt"] = pd.to_datetime(df["date"])
    return df


def attach_rate_axis(trades, rate_df):
    trades = trades.copy()
    trades["date_dt"] = pd.to_datetime(trades["date"])
    merged = pd.merge_asof(
        trades.sort_values("date_dt"), rate_df[["date_dt", "usTreasury10yChg6m"]],
        on="date_dt", direction="backward")
    return merged.drop(columns=["date_dt"])


def row_for(name, sub):
    s = group_stats(sub)
    if s is None:
        return {"구간": name, "거래수": 0}
    dpg = daily_portfolio_series(sub, "pnlGross")
    dpn = daily_portfolio_series(sub, "pnlNet")
    s["grossMeanBp"] = round(float(dpg.mean()) * 10000, 2) if len(dpg) else None
    s["netMeanBp"] = round(float(dpn.mean()) * 10000, 2) if len(dpn) else None
    s["mddPct"] = mdd_from_returns(dpn)
    s["구간"] = name
    return s


def main():
    print("분봉 로드 중...")
    base = load_base()
    print("base rows:", len(base), "날짜수:", base["date"].nunique())

    rate_df = load_rate_axis()

    lines = []
    lines.append("# Opening Fade — 미국 10년물 금리 hiking regime 조건부 확인 (2026-08)\n\n")
    lines.append(
        "PBR·CAND1 조사와 같은 축(미국 10년물 trailing 6개월/126거래일 변화, "
        "trailDays 동일 사전고정)을 Opening Fade에도 적용했다. 신호정의·체결"
        "규칙·비용가정(Q1롱+Q5숏, 09:05 진입, RT=30bp) 전부 무변경.\n\n"
        "**한계를 먼저 밝힌다**: 데이터 창이 2025-08-08~2026-08-21(약 1년)뿐"
        "이다 — CAND1과 같은 제약. PBR처럼 여러 해를 넘나드는 교차검증이 "
        "아니라 1년 안의 하위구간 비교다.\n\n---\n\n")

    for horizon in HORIZONS:
        lines.append("## %s\n\n" % horizon)
        trades = trades_for_horizon(base, horizon)
        trades = attach_rate_axis(trades, rate_df)
        n_no_axis = int(trades["usTreasury10yChg6m"].isna().sum())
        trades["hiking"] = trades["usTreasury10yChg6m"] > 0

        buckets = [("전체(baseline)", trades),
                   ("미국10Y 상승(hiking)", trades[trades["hiking"]]),
                   ("미국10Y 하락/정체", trades[~trades["hiking"] & trades["usTreasury10yChg6m"].notna()])]
        rows = [row_for(name, sub) for name, sub in buckets]
        tdf = pd.DataFrame(rows).set_index("구간")
        cols = ["trades", "tickers", "days", "winRate", "profitFactor",
                "grossMeanBp", "netMeanBp", "mddPct"]
        tdf = tdf.reindex(columns=cols)
        lines.append("| 구간 | 거래수 | 종목수 | 신호일수 | 승률 | Profit Factor | "
                      "gross(bp) | net(bp) | MDD(%) |\n")
        lines.append("|---|---|---|---|---|---|---|---|---|\n")
        for name, row in tdf.iterrows():
            lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n" % (
                name,
                "" if pd.isna(row["trades"]) else int(row["trades"]),
                "" if pd.isna(row["tickers"]) else int(row["tickers"]),
                "" if pd.isna(row["days"]) else int(row["days"]),
                "" if pd.isna(row["winRate"]) else "%.1f%%" % (row["winRate"] * 100),
                "" if pd.isna(row["profitFactor"]) else "%.2f" % row["profitFactor"],
                "" if pd.isna(row["grossMeanBp"]) else "%.2f" % row["grossMeanBp"],
                "" if pd.isna(row["netMeanBp"]) else "%.2f" % row["netMeanBp"],
                "" if pd.isna(row["mddPct"]) else "%.2f" % row["mddPct"],
            ))
        lines.append("\naxis 매칭 안 된 거래수: %d / %d\n\n" % (n_no_axis, len(trades)))
        print("[%s] baseline net=%.2fbp, hiking net=%s, not-hiking net=%s" % (
            horizon, rows[0].get("netMeanBp", float("nan")),
            rows[1].get("netMeanBp"), rows[2].get("netMeanBp")))

    lines.append(
        "## 검증 가능한 근거 목록\n\n"
        "- `opening_fade_macro_rate_regime_check.py` — 재실행하면 동일 결과\n"
        "- `analyze_opening_fade_regime_conditional.py` — `load_base`·"
        "`trades_for_horizon`·`group_stats`·`daily_portfolio_series`·"
        "`mdd_from_returns` 무변경 재사용\n"
        "- `pbr_macro_rate_regime_check.py`·`cand1_macro_rate_regime_check.py` "
        "— 동일 축·동일 trailDays(126) 원출처\n"
        "- `data/market-regime/market_regime_features.parquet` — usTreasury10y\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("\nwrote", OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
