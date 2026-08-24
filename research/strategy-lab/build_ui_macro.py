#!/usr/bin/env python
"""ui/data/macro.json 빌더 (매크로 탭). 두 기존 데이터셋을 그대로 재사용한다 -
새 수집 없음, KIS·시크릿 무관:

  1. research/strategy-lab/data/market-regime-feature-dataset/v1/
     features_daily.parquet - PIT-safe 시계열(환율·금리·나스닥·코스피 등),
     2026-08-14까지.
  2. docs/data/macro.json - 운영 대시보드가 매일 갱신하는 미국 매크로
     레짐 스냅샷(yield curve·VIX·CAPE 등), 최신값만.

★ 금·은·S&P500·나스닥100(현재 usNasdaq은 FRED NASDAQCOM=나스닥종합, 100
아님)은 이 프로젝트 어디에도 데이터가 없다 - 지어내지 않고 "notAvailable"
목록으로 정직하게 남긴다(이 프로젝트 절대 규칙 1, "모르는 건 0이 아니다").

  python build_ui_macro.py
"""
import json
import os

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PARQUET_PATH = os.path.join(REPO_ROOT, "research/strategy-lab/data/market-regime-feature-dataset/v1/features_daily.parquet")
DOCS_MACRO_PATH = os.path.join(REPO_ROOT, "docs/data/macro.json")
OUT_PATH = os.path.join(REPO_ROOT, "ui", "data", "macro.json")
HISTORY_SESSIONS = 250  # 약 1년치 - 라인차트용

SERIES = {
    "usdKrwLevel": "환율 (USD/KRW)",
    "vixLevel": "VIX",
    "usFedFundsRate": "미국 기준금리",
    "usTreasury10y": "미국 10년물 국채금리",
    "usNasdaq": "나스닥 종합지수 (FRED NASDAQCOM - 나스닥100 아님)",
    "krKospi": "코스피",
    "krTreasury3y": "한국 3년물 국채금리",
    "krCorpAA3y": "한국 회사채(AA-) 3년물",
    "krCpi": "한국 소비자물가지수",
    "krCreditSpreadBp": "한국 신용스프레드(bp)",
}
NOT_AVAILABLE = ["gold", "silver", "sp500", "nasdaq100"]


def main():
    df = pd.read_parquet(PARQUET_PATH).tail(HISTORY_SESSIONS)
    series = {}
    for col, label in SERIES.items():
        rows = df[["date", col]].dropna()
        series[col] = {
            "label": label,
            "history": [{"date": str(r["date"]), "value": float(r[col])} for _, r in rows.iterrows()],
        }

    us_regime = None
    if os.path.exists(DOCS_MACRO_PATH):
        with open(DOCS_MACRO_PATH, encoding="utf-8") as f:
            us_regime = json.load(f).get("indicators")

    out = {
        "seriesAsOf": str(df["date"].max()),
        "series": series,
        "usRegimeSnapshot": us_regime,  # docs/data/macro.json 그대로, 최신값만
        "notAvailable": NOT_AVAILABLE,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"저장: {OUT_PATH} (시리즈 {len(series)}개, 미보유 {len(NOT_AVAILABLE)}개)")


if __name__ == "__main__":
    main()
