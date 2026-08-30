---
track: kr
factor: integrated-research-inventory
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["market_regime_features", "regime_labels", "5DC-v1A-P", "VIX ETN", "TREND-BREAKOUT-v1", "CAND1"]
reason: "Market Regime 데이터축 실측과 기존 전략의 regime 결합 키를 읽기 전용 감사로 정리한 인벤토리 — 거래별 테이블이 남은 전략은 5DC·VIX ETN뿐이고 나머지는 재실행 필요"
---

# 통합 연구 인벤토리 — Market Regime 축 × 기존 전략 (2026-08-23)

산출: reports/2026-08-23-regime-integration-suite/{regime_integration_analysis.py,
integration_result.json}. 읽기 전용 감사.

## A. Market Regime 데이터축 (실측)

| 자료 | 파일(data/market-regime/) | 기간 | rows | PIT |
|---|---|---|---|---|
| market_regime_features | market_regime_features.parquet | 2016-01-04~2026-08-14 | 2,604×44컬럼 | AsOfDate provenance 전 컬럼 |
| regime_labels | regime_labels.parquet | 동일 | 2,604 | usableFromDate(date+1 기준, 주말 조정) |
| trend/breadth/rvol | trend·breadth·realized_vol.parquet | 동일 | 각 2,604 | 파생(A2a 종가) |
| turnover | turnover_value.parquet | 동일 | 2,604 | A4 마감 확정치 |
| flow | foreign_flow·institution_flow.parquet | 동일 | 각 2,604 | A4 확정치 |
| dispersion/corr | dispersion·correlation.parquet | 동일 | 각 2,604 | 파생 |
| VIX | vix_daily_kr.parquet | 2014-01~2026-08-14 | 3,097 | asOf(FRED date<D) |
| USD/KRW | usdkrw_daily_kr.parquet | 2014-01~동일 | 3,097 | asOf 동일 |
| US 10Y/FedFunds | ustreasury10y_raw·usfedfundsrate_raw | 1962~/1954~ | 16,144/26,349 | raw(레이어 결합 시 asOf 적용 필요) |
| NASDAQ Composite | usnasdaq_raw.parquet | 1971-02~2026-08-21 | 14,004 | raw |
| 한국 금리·신용스프레드 | krtreasury3y·krcorpaa3y_raw | 2014-01~ | 3,113 | raw |
| 한국 거시 | krcpi·krleadingcyclical·krcoincidentcyclical_raw | 월별/주간 | 151/150 | raw |

결측률: features 최대 1.50%(value_z60 워밍업), 나머지 0~0.35%.

## B. 기존 전략 자료와 regime 결합 키

| 전략 | 실제 파일 | 결과 형태 | 기간 | regime 결합 키 | 분해 가능 |
|---|---|---|---|---|---|
| 5DC-v1A-P(post-fix 정본) | reports/2026-08-16-parallel-validation/deepseek/5dc_v1a_p_samebar_rerun.json allTrades | **거래별 테이블(1,592건)**: entry/exit/pnl | 2014-05~2026-08 | exit_date→regime_labels.date | **완료(§2단계)** |
| TREND-BREAKOUT-v1 | reports/2026-08-15-trend-breakout-v1-smoke-postfix/*.json | 집계만(closedPositionCount 등, 거래 행 없음) | - | - | 재실행 필요(기존 산출물 덮어쓰기 주의) |
| CAND1 | findings/cand1-regime-decomposition/study_results.json | 집계만(자체 변동성 프록시 분해) | - | - | 원본 프레임 미보관으로 재실행 필요 |
| V3 BB+RSI / V5 / V6 / V7 / V8 | findings/*/signal_study_results.json | 호른즈별 집계만 | - | - | 재실행 필요 |
| VIX ETN | data/etp/vix/events.parquet | **이벤트별 테이블(129건)** | 2024-08~2026-03 | event_date→date | **완료(vix-etn-regime 문서)** |
| minute 3B | 본 세션 검증 JSON | 집계 컷만 | - | - | 재집계 가능(원시 신호 재계산 필요) |

핵심: 거래별 테이블이 남아 있는 전략은 5DC와 VIX ETN뿐이다. 나머지는 집계 JSON이라
국면 분해를 하려면 산출물 덮어쓰지 않는 별도 경로로 신호를 재생성해야 한다.
