---
track: macro
factor: us-market-data-gap
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "미국시장 데이터 갭 우선순위 - S&P500(FRED 10년+Stooq) 1순위, NDX100 2순위, 미국 breadth는 보류, 개별종목은 범위 밖"
---
# 미국시장 데이터 갭 최종 우선순위 (2026-08-23)

수집은 하지 않고 소스 조사만. 우선순위 순서대로.

## 1순위 — S&P 500 지수

| 항목 | 평가 |
|---|---|
| 무료 소스 | ①FRED `SP500` 시리즈(프로젝트 fred() 함수 그대로 재사용 가능) ②Stooq `^spx` CSV(비공식, 장기) |
| historical coverage | FRED: **최근 10년 한정**(FRED 정책). Stooq: 수십 년(비공식 품질 주의) |
| survivorship | 없음(지수 자체) |
| PIT | 지수 종가는 미국 마감 후 산출 → 한국 D+1 새벽 가용. 기존 asOf(date<D) 규칙과 동일 구조로 통제 가능(macro_common 재사용) |
| 데이터 품질 | 공식 지수값(배당 미포함 PR 계열) |
| 연결 가능성 | macro_layer_daily_kr에 usSp500 컬럼 추가하는 형태(usNasdaq 선례와 동일) |

권고: **FRED SP500(10년)+Stooq(장기 보조) 병행**. 10년은 우리 A2a 커버리지(2014-05+)의
절반이지만 VIX z≥+2 이벤트 150건 대부분을 포함한다.

## 2순위 — NASDAQ-100 지수

| 항목 | 평가 |
|---|---|
| 무료 소스 | FRED `NASDAQ100` 시리즈(1986~현재, 무료). Stooq `^ndx` 보조 |
| coverage | FRET/FRED 경로로 장기 확보 가능 |
| survivorship | 없음(지수 리밸런싱은 방법론 변경으로 기록됨) |
| PIT | 동일(asOf 규칙) |
| 품질 | 공식 지수 |
| 연결 | usNasdaq(Composite)과 별도 컬럼 병기 권장 |

Composite이 이미 있으므로 NDX100은 "성장주 국면 분리"가 필요해질 때 추가하면 된다.

## 3순위 — 미국 breadth

| 항목 | 평가 |
|---|---|
| 무료 소스 | **없음에 가까움** — S&P500 전종목 일별 고가/저가·MA 데이터가 필요(개별종목 수집 = 대규모 인프라). Barchart 등 유료 참고 |
| coverage | - |
| survivorship | 구성종목 변동 이슈 존재 |
| PIT | 개별 데이터 기반 산출 필요 |
| 판정 | **보류** — 한국 breadth(이미 구축)로 대체하고 미국 breadth는 P3 |

## 4순위 — 미국 개별종목

이번 단계 범위 밖. 미국 지수 축이 먼저고, 개별종목은 필요성이 입증된 후 별도 설계.
