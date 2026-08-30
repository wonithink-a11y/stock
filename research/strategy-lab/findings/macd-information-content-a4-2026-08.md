---
track: kr
factor: macd-information-content
date: 2026-08-26
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "MACD 관례적 사용(bullish cross)은 전 horizons 음의 초과수익으로 채택 가치 없음, 역전 macd_pct만 저순위 후보(독립성 미확인) - 관측 문서"
---
# MACD(12,26,9) 정보력 검증 — A4 연구 데이터셋 (2026-08-26)

작성: Ox Alpha 세션 (opencode/x-preview-f-free --variant max)
성격: 관측치 문서 — 채택 판단은 Claude·사용자 몫 (AGENTS.md §2·§4)
지시: "MACD 전략을 바로 채택하는 것이 아니라, MACD feature가 향후 주가수익률에
실제 정보력을 갖는지 검증". production 무변경, 새 수집 없음, divergence 제외.

- 스크립트: `research/strategy-lab/macd_information_content_study.py`
- 결과 JSON: `reports/2026-08-26-macd-information-content/macd-results.json`
- 재사용: momentum_decile_analysis.py(월간 리밸런스·날짜별 decile·양/음 분할),
  analyze_a4_research.py(일별 cross-sectional IC+t), build_a4_research_dataset.py
  (forward return PIT 규약) — 코드 패턴 재사용, 결과는 독립 산출

## 1. 데이터/표본

| 항목 | 값 |
|---|---|
| 표본 정의 | A4 research dataset 패널 행 (`data/a4/a4-research-dataset.parquet`) |
| 행 수 | 5,348,454 (중복 0) |
| 종목 | 2,558 |
| 기간 | 2016-01-04 ~ 2026-08-03 |
| 가격 | A2a 수정주가. **특징값 계산 기준은 종목별 전체 세션 캘린더**(A2a 원본 gz 스트리밍, full-series rows=5,850,437) |
| 월간 리밸런스 | 패널 달력의 월별 첫 세션 |
| forward return | close[t+h]/close[t]-1, h=20/60/120(decile)·5/20/60(event), 신호는 t 종가 |

**v1→v2 수정 사유(무결성)**: v1은 A4 패널 행 시퀀스 위에서 EMA/forward를
계산했는데, parquet fwd와 대조해 최대 편차 22(+2200%p) 발견 — 원인은
가격-패널 갭에서 h번째 행≠h거래일 뒤. v2는 전체 세션 캘린더 위에서 재계산해
**parquet fwd_d20/d60/d120와 maxAbsDiff=0.0으로 완전 일치**(정의 동일성 검증).

## 2. PIT 검증

1. **절단 재계산 단언**: 각 종목 계열 앞 60%만 잘라 MACD를 다시 만들면 전체
   계열 값과 정확히 같아야 한다 → 실측 최대 편차 **0.000e+00** (표본 40종목).
   ewm(span, adjust=False) 순차 재귀 + diff만 사용이라 구조적으로도
   backward-only.
2. **당일 신호 금지**: 모든 수익률이 t+h 대비 t 종가. cross 플래그도 t,t-1 두
   값만 사용.
3. **forward return 정의 검증**: parquet 내장 fwd와 완전 일치(위 표).
4. 이벤트 유의성은 같은 날짜 전체 횡단면 평균 대비 초과수익을 날짜 클러스터로
   묶어 검정 — 시장 drift·국면 혼입과 분리.

## 3. Feature별 결과

### 3.1 일별 cross-sectional Spearman IC (전 기간)

| feature | vs d20 | vs d60 | vs d120 |
|---|---|---|---|
| macd_pct (MACD/close×100) | **-0.0545** (t=-23.7) | -0.0487 (t=-24.2) | -0.0331 (t=-18.4) |
| hist_pct | -0.0190 (t=-10.1) | -0.0229 (t=-14.3) | -0.0134 (t=-8.4) |
| hist_chg_5d | -0.0083 (t=-4.8) | -0.0081 (t=-5.6) | -0.0057 (t=-3.9) |
| macd_slope_5d | -0.0148 (t=-7.7) | -0.0169 (t=-10.5) | -0.0073 (t=-4.7) |

nDays≈2,475~2,575. **전 feature 전 horizon에서 부호가 음(-)** — MACD가 높을수록
이후 수익률이 낮다. 통계적으로 매우 유의하지만 방향은 관례적 사용(추세 확인)과
정반대인 역전(contrarian).

### 3.2 연도별 안정성 (vs d60)

macd_pct: 2016 -0.076 · 2017 -0.021 · 2018 -0.111 · 2019 -0.056 · 2020 -0.051 ·
2021 -0.072 · 2022 -0.075 · 2023 -0.052 · 2024 -0.013 · **2025 +0.013 · 2026
+0.038** — 11년 중 9년 음, 최근 2년(AI 랠리 국면)만 양으로 반전. 장기 일관
역전이지만 최근 국면에서 부호 불안정.

### 3.3 월간 리밸런스 decile (Momentum12M 관례, D10=최고값)

**macd_pct D10-D1 spread (월별 시계열 기준)**:

| horizon | pooled | monthly mean | naive t | NW t | decile-return rho |
|---|---|---|---|---|---|
| d20 | -0.0110 | -0.0118 | **-2.52** | **-2.71** | -0.61 |
| d60 | -0.0157 | -0.0174 | -2.31 | -1.85 | -0.50 |
| d120 | -0.0027 | -0.0051 | -0.51 | -0.35 | -0.26 |

decile 평균(d20): D1 +0.69% … D9 +0.22%, **D10 -0.42%(승률 39.7%)** — 단조
감소라기보다 상위 극단(D9~D10, 특히 D10) 붕괴형. d60도 동일(D10 승률 37.8%,
중간 decile이 최고).

나머지 3개 feature의 D10-D1은 전부 \|NW t\|<2 (hist_pct d20 NWT +0.96,
hist_chg_5d d120 +1.35, macd_slope_5d d120 +1.76 등) — 유의 아님.

### 3.4 부호 상태 분할 (월간 시점, MACD>0 vs ≤0)

| horizon | pos mean(wr) | neg mean(wr) | 월별 차분 NW t |
|---|---|---|---|
| d20 | +0.15% (42.4%) | +0.61% (46.8%) | -1.78 |
| d60 | +1.24% (41.9%) | +1.94% (44.6%) | -1.38 |
| d120 | +3.21% (40.9%) | +4.14% (43.6%) | -0.04 |

방향은 "MACD≤0이 낫다"(역전)지만 유의성 기준 미달.

### 3.5 Event study (cross 후 5/20/60 거래일, 동일날짜 횡단면 대비 초과수익)

| event | n | d5 excess(t) | d20 excess(t) | d60 excess(t) |
|---|---|---|---|---|
| zeroCrossUp | 92,937 | -0.09% (-1.62) | -0.21% (-1.93) | -0.47% (**-2.81**) |
| zeroCrossDown | 93,768 | -0.19% (**-5.09**) | -0.67% (**-7.92**) | -0.65% (**-4.31**) |
| signalCrossUp | 206,881 | -0.15% (**-3.99**) | -0.10% (-1.42) | -0.32% (**-2.56**) |
| signalCrossDown | 206,980 | -0.18% (**-4.91**) | -0.45% (**-6.76**) | -0.55% (**-4.62**) |

핵심: **네 이벤트 전부 초과수익이 음**. bullish cross가 bearish cross보다 낫지
않다(오히려 bearish 쪽 d20 초과수익이 더 나쁨, 즉 방향 구분 없이 cross 자체가
"직전 큰폭 등락 마크"로서 이후 역전과 함께 감). raw 평균이 양(+0.2~+2.2%)으로
보이는 것은 시장 drift 효과로, 동일날짜 횡단면 대비에서는 전부 마이너스.
관례적 매수 트리거(zero/signal bullish cross)로서의 정보력은 없다.

## 4. 통계적 유의성 요약

- IC: 전 조합 \|t\|>3.9 (일별 IC의 t, nDays≈2.5천) — 다중검정 보정을 해도
  생존하나, **부호가 음**이라는 점이 본질.
- 월별 D10-D1: macd_pct d20만 NW t -2.71로 5% 유의(NW lag=h/21로 중첩창
  부분 보정), d60은 경계선(-1.85).
- 이벤트: 날짜 클러스터 t 기준 zero/signal cross 하이라이트 다수 \|t\|>4 —
  역시 전부 음의 초과수익.
- 중첩 forward window·횡단면 상관 미보정 한계는 caveats로 JSON에 명시.

## 5. 가장 유망한 feature

**macd_pct(레벨)** — 유일하게 견고한 신호. 단 방향은 문헌·본 프로젝트 전례와
일치하는 **역전**: 고MACD 종목 회피/저MACD 선호. 크기는 d20 D10-D1 월
-1.2%p 수준으로 작고, 효과가 D10 극단 집중형이며, 2025~2026 부호 반전.

단, 이 신호는 단기反전(REV20 계열)·유동성 버킷과 상관이 높을 가능성이 크다.
REV20의 교훈("알파는 저가·저유동성 종목 집중")과 PBR의 교훈("T1 버킷 소속
효과")을 고려하면, **REV20/유동성 필터 통제 후 독립 잔여정보가 남는지 확인하는
것이 다음 단계이며 그 전에 어떤 형태로도 채택 논의에 올리지 않는다**.

## 6. 채택 가치 판정 (이 세션 관측치)

- **기술적 진입 신호로서 MACD: 채택 가치 없음.** 관례적 사용(bullish cross
  매수·MACD>0 우위)은 KRX 2016~2026에서 전 horizons 음의 초과수익. V3
  (Bollinger+RSI)·TREND-BREAKOUT-v1 기각과 같은 결론 계열.
- **역전 feature(macd_pct) 후보: 연구 가치는 있으나 약함.** IC 크기는
  LOWMOM60(IC t≈5.2)·PBR(decile IC t=6.3) 대비 낮고, 최근 2년 부호 불안정,
  기존 反전 계열과의 독립성 미확인. 지금 Lab에 열려 있는 축(MAX 오버레이·PEAD)
  대비 우선순위 낮음.
- 권고: MACD 축은 여기서 종료하고, macd_pct는 "독립성 확인이 필요한 저순위
  후보 목록"에만 기록.

## 부록: 실행 환경

- Python 3.13.14, pandas/scipy. 실행 1회, 결정적(외부 난수 없음).
- v1(v패널행 기반) 결과는 v2로 대체됨 — v1 수치는 인용 금지(갭 치환 결함).
- production 코드 변경 0건, data/backfill 쓰기 0건, 신규 API 호출 0건.
