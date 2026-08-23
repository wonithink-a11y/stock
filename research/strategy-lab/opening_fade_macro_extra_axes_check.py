#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Opening Fade — 미검증 macro 6축 확장 검증 (2026-08).

배경: opening_fade_macro_rate_regime_check.py(2026-08)가 usTreasury10y 1축만
검증했다. market_regime_features.parquet의 아직 안 쓴 6축(usFedFundsRate·
usNasdaq·krKospi·krCpi·krLeadingCyclical·krCoincidentCyclical)에 **완전히 같은
방법론**을 그대로 적용한다 — 새 설계·임계값 결정 없음, 축 확장 반복.

**한계(먼저 밝힌다)**: 원본과 동일 — 분봉 캐시 전용이라 데이터 창이
2025-08-08~2026-08-21(약 1년)뿐이다. 1년 안의 하위구간 비교로만 해석한다.

방법: `analyze_opening_fade_regime_conditional.py`의 검증된 함수(`load_base`·
`trades_for_horizon`·`group_stats`·`daily_portfolio_series`·`mdd_from_returns`)
를 무변경 재사용한다. Opening Fade는 신호일 D 당일 09:05에 진입하므로 신호일 D를
parquet의 `date` 컬럼에 직접(asof-backward) 조인한다(parquet 축은 이미 PIT
시프트 완료, 중복 시프트 없음 — 원본과 동일). 각 축 trailing 126거래일 변화
(col - col.shift(126), threshold >0)로 버킷 비교. 신호정의·체결규칙·비용
(Q1롱+Q5숏, 09:05 진입, RT=30bp) 전부 무변경, trailDays=126 사전고정.

  python opening_fade_macro_extra_axes_check.py
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REGIME_PARQUET = HERE / "data" / "market-regime" / "market_regime_features.parquet"
OUT_MD = HERE / "findings" / "opening-fade-macro-extra-axes-2026-08.md"
TRAIL_DAYS = 126  # 원본 조사들과 동일 사전고정(재최적화 없음)
HORIZONS = ("T+5", "T+10")

sys.path.insert(0, str(HERE))

from analyze_opening_fade_regime_conditional import (  # noqa: E402
    daily_portfolio_series, group_stats, load_base, mdd_from_returns, trades_for_horizon,
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
    df["date_dt"] = pd.to_datetime(df["date"])
    return df


def attach_axes(trades, axes_df):
    trades = trades.copy()
    trades["date_dt"] = pd.to_datetime(trades["date"])
    chg_cols = ["date_dt"] + [c + "Chg6m" for c, _ in EXTRA_AXES]
    merged = pd.merge_asof(
        trades.sort_values("date_dt"), axes_df[chg_cols],
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
    t0 = time.time()
    print("분봉 로드 중...")
    base = load_base()
    print("base rows:", len(base), "날짜수:", base["date"].nunique(), "(%.0fs)" % (time.time() - t0))

    axes_df = load_extra_axes()

    results = {}
    lines = []
    lines.append("# Opening Fade — 미검증 macro 6축 확장 검증 (2026-08)\n\n")
    lines.append(
        "opening_fade_macro_rate_regime_check.py(미국 10년물 1축)에 이어, 아직 안 쓴 "
        "macro 6축(연방기금금리·나스닥·KOSPI·한국 CPI·선행순환지수·일반순환지수)에 "
        "**완전히 같은 방법론**을 적용했다. 신호정의·체결규칙·비용가정(Q1롱+Q5숏, "
        "09:05 진입, RT=30bp) 전부 무변경, trailDays=%d 사전고정.\n\n" % TRAIL_DAYS)
    lines.append(
        "**한계를 먼저 밝힌다**: 데이터 창이 2025-08-08~2026-08-21(약 1년)뿐이다 — "
        "원본과 같은 제약. PBR처럼 여러 해를 넘나드는 교차검증이 아니라 1년 안의 "
        "하위구간 비교다.\n\n---\n\n")

    cols = ["trades", "tickers", "days", "winRate", "profitFactor",
            "grossMeanBp", "netMeanBp", "mddPct"]
    for horizon in HORIZONS:
        results[horizon] = {}
        trades0 = trades_for_horizon(base, horizon)
        merged_all = attach_axes(trades0, axes_df)
        lines.append("## %s\n\n" % horizon)
        print("\n[%s]" % horizon)
        for col, label in EXTRA_AXES:
            chg_col = col + "Chg6m"
            n_no_axis = int(merged_all[chg_col].isna().sum())
            sub_up = merged_all[merged_all[chg_col] > 0]
            sub_not = merged_all[merged_all[chg_col] <= 0]
            rows = [row_for("전체(baseline)", merged_all),
                    row_for("%s 상승(up)" % label, sub_up),
                    row_for("%s 하락/정체(not)" % label, sub_not)]
            results[horizon][chg_col] = {
                "label": label,
                "tradesNoAxis": n_no_axis,
                "rows": [{k: (v if not isinstance(v, float) else round(float(v), 4))
                          for k, v in r.items()} for r in rows],
            }
            tdf = pd.DataFrame(rows).set_index("구간").reindex(columns=cols)
            lines.append("### %s — trailing %d거래일 변화 >0 여부\n\n" % (label, TRAIL_DAYS))
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
            lines.append("\naxis 매칭 안 된 거래수: %d / %d\n\n" % (n_no_axis, len(merged_all)))
            print("  [%s] baseline net=%s | up net=%s | not net=%s" % (
                label, rows[0].get("netMeanBp"), rows[1].get("netMeanBp"),
                rows[2].get("netMeanBp")))

    lines.append("---\n\n## 검증 가능한 근거 목록\n\n")
    lines.append(
        "- `opening_fade_macro_extra_axes_check.py` — 재실행하면 동일 결과\n"
        "- `analyze_opening_fade_regime_conditional.py` — `load_base`·"
        "`trades_for_horizon`·`group_stats`·`daily_portfolio_series`·"
        "`mdd_from_returns` 무변경 재사용\n"
        "- `opening_fade_macro_rate_regime_check.py` — 동일 방법론 원출처(usTreasury10y 축)\n"
        "- `data/market-regime/market_regime_features.parquet` — 6축 원천\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("\nwrote", OUT_MD)

    out_dir = HERE / "reports" / "2026-08-24-opening-fade-macro-extra-axes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "opening-fade-macro-extra-axes.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "Opening Fade 미검증 macro 6축 확장 검증 - "
                       "opening_fade_macro_rate_regime_check.py와 동일 방법론의 축 확장 반복",
            "trailDays": TRAIL_DAYS,
            "results": results,
        }, fh, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
