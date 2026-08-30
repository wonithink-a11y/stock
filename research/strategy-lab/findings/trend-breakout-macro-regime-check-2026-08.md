---
track: kr
factor: trend-breakout-macro-regime-check
date: 2026-08-24
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["trailing_126d_change_gt0", "monthly_mtm", "absolute_return"]
reason: "TREND-BREAKOUT-v1 손실은 KOSPI 약세·미국10Y 상승·신용스프레드 확대 창에 집중(ex-2022 방향 유지) - 절대수익 기준 손실의 조건화, 편입 판단 없음"
cagr: -13.30
sharpe: -0.73
mdd: -77.92
n: 128
---
# TREND-BREAKOUT-v1 — macro regime 축별 조건부 성과 검증 (2026-08-24)

배경: `pbr_macro_rate_regime_check.py`(2026-08-23)가 검증한 방법론 — 월별 수익을
"trailing 126거래일 변화"의 부호(hiking>0 / not-hiking<=0)로 분류해 평균수익·
기여율을 비교 — 를 아직 한 번도 적용한 적 없는 Strategy Lab 전략
**TREND-BREAKOUT-v1**에 그대로 적용했다(축 10개 전부: usFedFundsRate·
usTreasury10y·usNasdaq·krKospi·krTreasury3y·krCorpAA3y·krCpi·krLeadingCyclical·
krCoincidentCyclical·krCreditSpreadBp). LOWMOM60 조사와 마찬가지로 절대수익 기준이다.

방법: `run_smoke()` + `pbr_vs_ew_monthly_mtm.py::curve_metrics`는 무변경 재사용,
월말 종가 MTM 스냅샷 day-loop는 `engine/runner.py::_schedule_portfolio()`의
**현재 논리**(same-bar 재시도 + 2026-08-22 exit_symbols_queued 가드)를 그대로
복제했다. `pbr_vs_ew_monthly_mtm.schedule_with_monthly_mtm`의 사본은 이 가드가
반영되기 전 버전이라 동일심볼 청산+재진입 체인이 same-bar 스탑까지 겹치는 날에
exits 큐에 같은 심볼이 두 번 들어가 process_day()에서 KeyError가 났다
(trend_breakout_v1 실측, 001770) — 기존 스크립트 수정 금지이므로 새 스크립트 안에
엔진 현재 논리 기준으로 복제해 해결했다(원본 파일 무변경).
`market_regime_features.parquet`의 각 축에 trailing 126거래일 변화
(`col - col.shift(126)`)를 계산해 `merge_asof(backward)`로 PIT 안전하게 조인했다.
**threshold 재최적화 없음**(126거래일·>0 사전 고정, 전 축 같은 창), 정규화 없음,
production 코드·정책 무변경.

**신규 스크립트**: `trend_breakout_macro_regime_check.py`

---

## 0. baseline 먼저 — 이 표는 알파 근거가 아니다

2016-01~2026-08 엔진 MTM 기준 trend_breakout_v1은 **CAGR -13.30% · totalReturn
-77.92% · MDD -77.92% · Sharpe -0.73**(128개월, 최종 자산 1억→2,208만원).
연도별로도 11개 연도 중 플러스는 2017(+2.9%)·2020(+10.2%)·2023(+15.0%)·
2025(+12.5%)뿐이고 2026년(~08)만 -30.7%다. 즉 아래 regime 분해는
**"손실이 어디에 몰리는가"의 지도**이지 전략의 타당성 근거가 아니다.

## 1. 결론 요약

전체 수익 합계 = -1.14595 (regime 데이터가 있는 122개월 단순합)

| 축 | hiking/not 월수 | hiking 기여율 | hiking 월평균 | not-hiking 월평균 |
|---|---|---|---|---|
| **KOSPI 지수** | 74/48 | **-3.20%** (역방향) | **+0.05%** | **-2.46%** |
| 한국 일반순환지수 | 60/62 | 98.77% | -1.89% | -0.02% |
| **한국 신용스프레드(확대)** | 70/52 | **87.75%** | **-1.44%** | -0.27% |
| **미국 10년물 금리** | 65/57 | **76.61%** | **-1.35%** | -0.47% |
| 한국 회사채 AA- 3년 | 65/57 | 72.70% | -1.28% | -0.55% |
| 한국 국고채 3년 | 64/58 | 65.76% | -1.18% | -0.68% |
| 나스닥 지수 | 99/23 | 63.90% | -0.74% | -1.80% |
| 미국 연방기금금리 | 68/54 | 58.47% | -0.99% | -0.88% |
| 한국 선행순환지수 | 58/64 | 52.42% | -1.04% | -0.85% |
| 한국 CPI | 113/9 | 109.40% | -1.11% | +1.20% |

## 2. 유의미한 축 — KOSPI(역방향)·미국 10년물·신용스프레드

- **KOSPI**: 유일하게 hiking 버킷 합계가 플러스(+0.037)인 축이다. KOSPI trailing
  6개월 상승 구간에서는 월평균 +0.05%로 손익분기, 하락/정체 구간에서는
  **-2.46%/월** — 손실이 전부 시장 약세 창에서 나온다는, 롱 브레이크아웃답게
  가장 경제적으로 자명한 패턴이다. 단 방향이 한쪽만 성립한다: KOSPI 하락
  과반 해(2018 3/12 -0.279 · 2019 4/12 -0.142 · 2022 0/12 -0.379)는 전부
  예측대로 빨갛지만, 역은 성립하지 않는다(2024 7/12 -0.198 · 2026 8/8 -0.308).
  "시장 오르면 오른다"가 아니라 **"시장 안 오르면 반드시 죽는다"**에 가깝다.
- **미국 10년물**: hiking 65개월 -1.35%/월 vs not-hiking 57개월 -0.47%/월,
  기여율 76.61%. 2022년(12/12 hiking, retSum -0.379)을 빼도 hiking 합계
  -0.499 vs not-hiking -0.268로 **방향 ex-2022 유지** — PBR-EW 초과수익이
  미국 금리 상승기에 살았다는 것과 거울상으로, 브레이크아웃 모멘텀 롱은 같은
  regime에서 추가로 깎인다.
- **신용스프레드 확대**: hiking 70개월 -1.44%/월 vs not 52개월 -0.27%/월,
  기여율 87.75%. ex-2022에도 -0.627 vs -0.140으로 방향 유지. 위험 프리미엄
  확대기에 브레이크아웃 추격이 특히 잘 잘린다는 해석과 일치.

## 3. 주의가 필요한 축

- **한국 일반순환지수**: 기여율 98.77%(hiking -1.89% vs not -0.02%)로 표면상
  최강이지만, 2017년(12/12 hiking, +0.031)·2025년(4/12, +0.127) 등 반례가 있고
  "경기순환지수 상승기에 국내주식 브레이크아웃이 더 못 번다"는 서사는 직관과
  어긋난다 — 신호라기보다 손실 연도들의 우발적 겹침 가능성을 배제할 수 없다.
- **한국 국고채 3년**: 월별로는 65.76%지만 **2022년을 빼면 방향이 소멸**
  (hiking ex-2022 -0.375 vs not -0.392) — 이 축의 집중은 2022년 하나로 설명된다.
  회사채 AA- 3년은 ex-2022에도 방향 유지(-0.454 vs -0.313)지만 격차가 크게 줄었다.

## 4. 무의미했던 축

- **한국 CPI**: 122개월 중 113개월이 hiking — 분할 실패(not 9개월 표본), LOWMOM60
  때와 동일 결론.
- **나스닥**: 99/23 치우친 분할 + 방향 반대(not-hiking 쪽이 더 나쁨) — 23개월
  표본으로는 판단 불가.
- **연방기금금리·선행순환지수**: 양쪽 버킷 차이가 월 0.1~0.2%p 수준으로 사실상 중립.

## 5. 종합 판단

1. TREND-BREAKOUT-v1의 손실은 **KOSPI 약세 창·미국 10년물 상승 창·신용스프레드
   확대 창**에 집중되며, 세 축 모두 ex-2022 방향이 유지된다. 특히 KOSPI는
   유일한 플러스 버킷 축으로, 이 전략이 시장 베타 노출 그 자체임을 숫자로 확인시킨다.
2. 미국 10년물 결과는 PBR-EW(+방향)와 합치하면 "미국 금리 상승기에는 가치는
   덜 깎이고 브레이크아웃 모멘텀은 더 깎인다"는 같은 regime의 두 면이다 —
   다만 이번 조사는 절대수익 기준이라 베타 통제는 안 했다.
3. baseline이 CAGR -13.3%라는 점은 그대로다: regime 필터를 얹어도 "덜 망하는"
   방향의 정보일 뿐이고, 어떤 production 편입 판단도 이번 조사에서 하지 않는다.

## 6. 이번 조사가 하지 않은 것

- threshold 재최적화 없음 — 126거래일 창·>0 부호 규칙 사전 고정
- 다른 lag 스윕 없음, 연속형 변환 없음, KOSPI 베타 통제(절대수익 vs 시장수익
  분리) 없음
- day-loop 가드 복제 외의 engine·strategies·config·policy 변경 없음
- `pbr_vs_ew_monthly_mtm.py` 등 기존 파일 무변경(가드 없는 사본 함수를 고치지
  않고 새 스크립트 안에 엔진 현재 논리로 복제해 해결)

## 검증 가능한 근거 목록

- `trend_breakout_macro_regime_check.py` — 재실행하면 동일 결과(런타임 약 7분,
  A2A 캐시 사용)
- `reports/2026-08-24-trend-breakout-macro-regime/trend-breakout-macro-regime-check.json`
  — 원본 산출물(10축 bucket report + 연도별 breakdown + annualReturns)
- `engine/runner.py::_schedule_portfolio` — day-loop 복제 원천(exit_symbols_queued
  가드 포함 현재 논리)
- `pbr_vs_ew_monthly_mtm.py::curve_metrics/annual_returns_mtm` — 무변경 import 재사용
- `data/market-regime/market_regime_features.parquet` — 10개 축 원천(Macro Regime Layer 백필)
