#!/usr/bin/env python
"""ui/data/macro.json 빌더 (매크로 탭). 세 기존 데이터셋을 그대로 재사용한다 -
새 수집 없음, KIS·시크릿 무관:

  1. research/strategy-lab/data/market-regime-feature-dataset/v1/
     features_daily.parquet - PIT-safe 시계열(환율·금리·나스닥·코스피 등),
     2026-08-14까지.
  2. research/strategy-lab/data/market-regime/fred_extended_daily_kr.parquet -
     build_fred_extended_backfill.py 산출물(사용자 1차 우선순위: S&P500·
     나스닥100·2년물·10Y-2Y·하이일드 스프레드). 같은 KR 거래일 캘린더로
     조인돼 있어 날짜축이 #1과 그대로 맞는다 - 별도 재조인 없이 병렬로 읽는다.
  3. docs/data/macro.json - 운영 대시보드가 매일 갱신하는 미국 매크로
     레짐 스냅샷(yield curve·VIX·CAPE 등), 최신값만.

★ 금·은은 FRED가 라이선스 문제로 폐지해서(직접 확인함, 2026-08-25) 이
프로젝트 어디에도 데이터가 없다 - 지어내지 않고 "notAvailable" 목록으로
정직하게 남긴다(절대 규칙 1). S&P500·나스닥100은 #2 추가로 더 이상
notAvailable이 아니다.

  python build_ui_macro.py
"""
import json
import os

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PARQUET_PATH = os.path.join(REPO_ROOT, "research/strategy-lab/data/market-regime-feature-dataset/v1/features_daily.parquet")
FRED_EXT_PATH = os.path.join(REPO_ROOT, "research/strategy-lab/data/market-regime/fred_extended_daily_kr.parquet")
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
# 1차·2차 우선순위 추가분(fred_extended_daily_kr.parquet에서 읽음)
SERIES_EXT = {
    "usSp500": "S&P 500",
    "usNasdaq100": "나스닥 100",
    "usTreasury2y": "미국 2년물 국채금리",
    "usYieldSpread10y2y": "미국 10Y-2Y 금리차",
    "usHighYieldSpread": "미국 하이일드 스프레드",
    # 2차 - 전부 월별/분기별 경제지표(매일 안 바뀜, 아래 main() 하단 참고)
    "usCpi": "미국 CPI",
    "usPceCore": "미국 근원 PCE",
    "usUnemploymentRate": "미국 실업률",
    "usIndustrialProduction": "미국 산업생산지수",
    "usRealGdp": "미국 실질 GDP",
}
NOT_AVAILABLE = ["gold", "silver"]


def _series_from(df, spec):
    out = {}
    for col, label in spec.items():
        if col not in df.columns:
            continue
        rows = df[["date", col]].dropna()
        out[col] = {
            "label": label,
            "history": [{"date": str(r["date"]), "value": float(r[col])} for _, r in rows.iterrows()],
        }
    return out


def main():
    df = pd.read_parquet(PARQUET_PATH).tail(HISTORY_SESSIONS)
    series = _series_from(df, SERIES)

    if os.path.exists(FRED_EXT_PATH):
        df_ext = pd.read_parquet(FRED_EXT_PATH).tail(HISTORY_SESSIONS)
        series.update(_series_from(df_ext, SERIES_EXT))
    else:
        print(f"[경고] {FRED_EXT_PATH} 없음 - 1차 우선순위 지표 스킵 "
              f"(build_fred_extended_backfill.py 먼저 실행)")

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
