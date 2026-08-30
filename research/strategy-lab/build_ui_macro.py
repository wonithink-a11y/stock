#!/usr/bin/env python
"""ui/data/macro.json 빌더 (매크로 탭). 전부 이미 있는 소스를 그대로 읽는다 -
새 수집 없음, KIS·시크릿 무관:

  1. vix_daily_kr.parquet · usdkrw_daily_kr.parquet(build_vix_backfill.py ·
     build_usdkrw_backfill.py, FRED 무키)
  2. macro_layer_daily_kr.parquet(build_macro_layer_backfill.py, ECOS+Naver
     - usFedFundsRate·usTreasury10y·usNasdaq·krKospi·krTreasury3y·krCorpAA3y·
     krCpi·krCreditSpreadBp)
  3. fred_extended_daily_kr.parquet(build_fred_extended_backfill.py, FRED 무키)
  4. docs/data/macro.json - 운영 대시보드가 매일 갱신하는 미국 매크로
     레짐 스냅샷(yield curve·VIX·CAPE 등), 최신값만.

★ 2026-08-30 변경 - 이전엔 market_regime_features.parquet(A2a 6백만행
전량을 읽어 breadth/trend/correlation까지 계산하는 build_regime_features_
backfill.py의 산출물)을 거쳐 읽었다. 하지만 이 매크로 탭이 실제로 쓰는
필드(환율·VIX·금리·KOSPI 등 10+11개)는 전부 위 1~3번 소스에 이미 그대로
있고, breadth/trend/correlation은 애초에 SERIES/SERIES_EXT 어디에도 없다 -
안 쓰는 값을 얻으려고 로컬 실측 몇 분(완주 못 함, CI에서는 더 오래 걸릴
가능성)짜리 무거운 계산을 매일 돌릴 이유가 없었다. 1~3번은 전부 API
호출만 하는 가벼운 스크립트(로컬 실측 각 수 초~1분)라 매일 자동화에
적합 - .github/workflows/macro-regime-ui.yml.

★ 금·은은 FRED가 라이선스 문제로 폐지해서(직접 확인함, 2026-08-25) 이
프로젝트 어디에도 데이터가 없다 - 지어내지 않고 "notAvailable" 목록으로
정직하게 남긴다(절대 규칙 1). S&P500·나스닥100은 #3 추가로 더 이상
notAvailable이 아니다.

  python build_ui_macro.py
"""
import json
import os

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGIME_DIR = os.path.join(REPO_ROOT, "research/strategy-lab/data/market-regime")
DOCS_MACRO_PATH = os.path.join(REPO_ROOT, "docs/data/macro.json")
OUT_PATH = os.path.join(REPO_ROOT, "ui", "data", "macro.json")
HISTORY_SESSIONS = 250  # 약 1년치 - 라인차트용

# 파일명 -> {컬럼: 라벨}. 전부 "date" 컬럼 기준(트레이딩 캘린더 공통) - 순서대로
# 읽어 나중 파일이 같은 컬럼을 덮어써도 무해하다(지금은 중복 컬럼 없음).
SOURCES = {
    "vix_daily_kr.parquet": {"vixLevel": "VIX"},
    "usdkrw_daily_kr.parquet": {"usdKrwLevel": "환율 (USD/KRW)"},
    "macro_layer_daily_kr.parquet": {
        "usFedFundsRate": "미국 기준금리",
        "usTreasury10y": "미국 10년물 국채금리",
        "usNasdaq": "나스닥 종합지수 (FRED NASDAQCOM - 나스닥100 아님)",
        "krKospi": "코스피",
        "krTreasury3y": "한국 3년물 국채금리",
        "krCorpAA3y": "한국 회사채(AA-) 3년물",
        "krCpi": "한국 소비자물가지수",
        "krCreditSpreadBp": "한국 신용스프레드(bp)",
    },
    "fred_extended_daily_kr.parquet": {
        "krKosdaq": "코스닥",
        "usSp500": "S&P 500",
        "usNasdaq100": "나스닥 100",
        "usTreasury2y": "미국 2년물 국채금리",
        "usYieldSpread10y2y": "미국 10Y-2Y 금리차",
        "usHighYieldSpread": "미국 하이일드 스프레드",
        # 아래 4개는 월별/분기별 경제지표(매일 안 바뀜)
        "usCpi": "미국 CPI",
        "usPceCore": "미국 근원 PCE",
        "usUnemploymentRate": "미국 실업률",
        "usIndustrialProduction": "미국 산업생산지수",
        "usRealGdp": "미국 실질 GDP",
    },
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
    series = {}
    latest_date = None
    for fname, spec in SOURCES.items():
        path = os.path.join(REGIME_DIR, fname)
        if not os.path.exists(path):
            print(f"[경고] {path} 없음 - {list(spec)} 스킵")
            continue
        df = pd.read_parquet(path).tail(HISTORY_SESSIONS)
        series.update(_series_from(df, spec))
        d = str(df["date"].max())
        latest_date = d if latest_date is None else max(latest_date, d)

    us_regime = None
    if os.path.exists(DOCS_MACRO_PATH):
        with open(DOCS_MACRO_PATH, encoding="utf-8") as f:
            us_regime = json.load(f).get("indicators")

    out = {
        "seriesAsOf": latest_date,
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
