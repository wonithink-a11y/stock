---
track: kr
factor: pbr-macro-extra-axes
date: 2026-08-24
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["usFedFundsRate", "usNasdaq", "krKospi", "krCpi", "krLeadingCyclical", "krCoincidentCyclical"]
reason: "미검증 macro 6축 중 한국 일반순환지수만 생존(2022 제외에도 방향 유지, up +0.52%/월) - 나머지 5축은 역방향·2022 단독·버킷 붕괴로 근거 불가, 생존축도 연도별 반례 4개"
---
# PBR-EW — 미검증 macro 6축 확장 검증 (2026-08-24)

`pbr_macro_rate_regime_check.py`(2026-08-23)가 usTreasury10y·krTreasury3y·
krCreditSpreadBp 3축만 검증했으므로, `market_regime_features.parquet`의 아직
안 쓴 6축(usFedFundsRate·usNasdaq·krKospi·krCpi·krLeadingCyclical·
krCoincidentCyclical)에 **완전히 같은 방법론**을 적용했다 — 새 설계·임계값
결정 없음, 이미 검증된 패턴의 축 확장 반복.

방법: `pbr_macro_rate_regime_check.py`와 동일. `pbr_vs_ew_monthly_mtm.py`의
`schedule_with_monthly_mtm`을 무변경 재사용해 월별 MTM 초과수익(PBR-EW,
128개월 중 axis 확보 122개월)을 재현하고, 각 축의 trailing 126거래일(~6개월)
변화(`col - col.shift(126)`, threshold >0)로 버킷을 나눈다. TRAIL_DAYS=126
사전고정(재최적화 없음), production 코드·정책 무변경.

**신규 스크립트**: `pbr_macro_extra_axes_check.py`

---

## 결과 요약

| 축 | up월/전체 | up 월평균 | not-up 월평균 | 2022 제외 시 | 판정 |
|---|---|---|---|---|---|
| 미국 연방기금금리 | 68/122 | +0.16% | +0.05% | **역전**(up합 -0.053) | 2022 하나로 설명 |
| 나스닥 지수 | 99/122 | -0.03% | +0.71% | — | **역방향** |
| KOSPI 지수 | 74/122 | -0.12% | +0.46% | — | **역방향** |
| 한국 CPI | 113/122 | +0.22% | -1.23% | 유지(+0.083) | **버킷 붕괴**(not-up 9개월뿐) |
| 한국 선행순환지수 | 58/122 | -0.07% | +0.27% | — | **역방향** |
| **한국 일반순환지수** | 60/122 | **+0.52%** | **-0.29%** | **유지**(up합 +0.154 vs not -0.181) | **유일한 생존 축** |

## 한국 일반순환지수 축 — 연도별 breakdown

| 연도 | up월/전체 | 초과수익 | 패턴과 일치? |
|---|---|---|---|
| 2016 | 3/6 | +0.021 | 혼합 |
| 2017 | 12/12 | -0.014 | **불일치**(과반 up인데 음수) |
| 2018 | 2/12 | +0.038 | **불일치**(대부분 not-up인데 양수) |
| 2019 | 2/12 | -0.011 | 일치(대부분 not-up, 음수) |
| 2020 | 4/12 | -0.080 | 일치(대부분 not-up, 음수) |
| 2021 | 12/12 | +0.072 | 일치 |
| **2022** | 12/12 | **+0.161** | 일치(단일 최대 기여) |
| 2023 | 5/12 | -0.045 | 혼합 |
| 2024 | 1/12 | +0.067 | **불일치** |
| 2025 | 4/12 | -0.007 | 중립 |
| 2026(~08) | 3/8 | -0.068 | **불일치** |

## 해설

6축 중 **한국 일반순환지수(trailing 6개월 변화)만이 원본 미국 10년물 축과 같은
구조를 보인다** — 월별 집계에서 뚜렷한 방향(up +0.52%/월 vs not-up
-0.29%/월)이 있고, 2022년(+0.161, 12/12 up)을 빼도 방향이 유지된다(up합
+0.154 vs not-up -0.181). 경제적으로도 자연스럽다 — 한국 동행경기순환이
오르는 국면에서 PBR이 EW를 이긴다는 것은 원본 조사의 "미국 금리 상승기
조건부 가치주 노출"과 함께 리스크온 국면 조건부라는 단서를 더 좁혀준다.
단, 연도별로 보면 2017·2018·2024·2026이 명확한 반례라서 원본 미국10Y 축과
마찬가지로 "깨끗한 인과관계"라고 할 수는 없다.

나머지 5축은 근거가 되지 못한다. 연방기금금리는 표면적으로 방향이 맞지만
2022년을 빼면 부호가 뒤집힌다(원본 국고채3년·신용스프레드와 같은 운명).
나스닥·KOSPI·선행순환지수는 아예 반대 방향이다. CPI는 not-up 버킷이 9개월
뿐(2017-12, 2019년 봄, 2019-12, 2020년 여름에 흩어진 월들)이라 월평균
-1.23%가 그 9개월의 이상치에서 전부 나오는 구조라 regime 규칙으로 보기
어렵다.

## 이번 조사가 하지 않은 것

- threshold 재최적화 없음 — 126거래일(6개월) 창 사전 고정
- 다른 lag 스윕 없음 — 필요하면 별도 조사
- 일반순환지수 축을 regime 점수식에 편입할지 결정 안 함(macro-regime-layer
  -design-2026-08.md §8과 같은 경계)
- PBR 실전 배포 결정 안 함 — 여전히 연구 후보

## 검증 가능한 근거 목록

- `pbr_macro_extra_axes_check.py` — 재실행하면 동일 결과(런타임 약 3분,
  PBR·EW 각각 run_smoke() 재계산)
- `reports/2026-08-24-pbr-macro-extra-axes/pbr-macro-extra-axes.json`
  — 원본 산출물(연도별 breakdown 전체 포함)
- `pbr_vs_ew_monthly_mtm.py::schedule_with_monthly_mtm` — 무변경 재사용,
  월별 MTM 스냅샷 원출처
- `pbr_macro_rate_regime_check.py` — 동일 방법론 원출처(기존 3축)
- `data/market-regime/market_regime_features.parquet` — 6축 원천(Macro
  Regime Layer 백필)