---
track: kr
factor: earnings_yield
subproject: factor-discovery-kr-2026-08 (후속 검증)
date: 2026-09-02
verdict: PASS
criteria_version: oos-split-v1
conditions: [earnings_yield, TRAIN=2016-01~2022-06, VALID=2022-06~2024-01, TEST=2024-01~2026-08]
reason: >-
  IC t-stat이 TRAIN 4.07 / VALID 3.31 / TEST 3.64로 세 구간 전부 통상 유의성
  기준(t>=2)을 넘김; decile slope도 0.745/0.576/0.758로 부호반전 없음; TEST의
  Q10-Q1 net CAGR 스프레드(+10.79% vs -9.52%)가 세 구간 중 가장 크다 -
  신호가 최근 구간에서 약해지지 않고 오히려 강해짐.
---

# Earnings Yield — TRAIN/VALID/TEST 분해 검증 (기존 PASS의 남은 구멍 메움)

## 0. 배경 — 왜 이 검증이 필요했나

`factor-earnings-yield-portfolio-validation-2026-08.md`(2026-08-30)가 이미
"PASS, 즉시 운용 가능"으로 결론 냈지만, 그 문서의 핵심 통계(IC t=6.10,
decile slope 0.867)는 **TRAIN/VALID/TEST를 나누지 않은 전체기간 풀링값**
이었다. 114행에 "Periods: TRAIN 46063, VALID 13713, TEST 23312"라고 구간
개수만 적혀 있을 뿐, TEST(진짜 out-of-sample)만 따로 봤을 때도 신호가
살아있는지는 확인된 적이 없었다.

이 프로젝트는 REV20·Opening Fade·PEAD·PBR 라인에서 반복적으로 "전체기간
풀링으로는 강해 보이던 신호가 TEST 구간에서 부호 반전되거나 유의성을
잃는다"는 패턴을 겪었고, 그때마다 이 분해 검증이 최종 채택/기각을 갈랐다.
같은 표준을 여기도 적용한다.

## 1. 방법

- `factor_discovery_kr.py`의 `decile_analysis()`를 **그대로 재사용**
  (새 계산식을 안 만든다 - 전체기간 수치와 자동으로 비교 가능하게)
- base 구성도 원본과 동일 규약(A4 종가·거래대금, PIT valuation-panel의
  `per`, fwd1m = 신호 다음 거래일 진입 → 다음 리밸런스월 첫 거래일 청산,
  유동성 게이트 dv20≥1억원)
- period 경계는 원본과 동일: TRAIN ≤2022-06-30, VALID ≤2024-01-01, TEST 이후
- 스크립트: `factor_earnings_yield_train_valid_test.py`

## 2. 결과

| 구간 | n | 개월 | IC 평균 | **IC t** | decile slope | Q10-Q1 스프레드(월) | 스프레드 t | Q10 net CAGR | Q1 net CAGR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ALL(풀링, 기존 문서 재확인) | 83,088 | 124 | 0.0563 | 6.10 | 0.867 | +0.76% | 2.27 | +2.68% | -7.08% |
| TRAIN | 46,063 | 75 | 0.0455 | **4.07** | 0.745 | +0.46% | 1.22 | -0.17% | -6.12% |
| VALID | 13,713 | 18 | 0.0541 | **3.31** | 0.576 | +0.66% | 0.90 | +1.32% | -6.77% |
| TEST | 23,312 | 31 | 0.0838 | **3.64** | 0.758 | +1.57% | 1.73 | **+10.79%** | **-9.52%** |

- ALL 풀링 수치(IC t=6.10, slope=0.867)는 정확히 재현됨(기존 문서와 소수점
  일치) - 재현성 확인.
- **세 구간 전부 IC t≥2(통상 유의성 기준) 통과** - VALID가 가장 약해도
  t=3.31로 여유 있게 넘음.
- decile slope 부호반전 0건(0.745/0.576/0.758 전부 양수).
- **TEST(2024-01~2026-08, 가장 최근·진짜 OOS)가 IC 평균·스프레드 크기
  기준으로 오히려 가장 강하다** - 신호 감쇠(decay) 없음. REV20·Opening
  Fade가 겪은 "TEST 반전" 패턴이 여기서는 재현되지 않았다.
- Q10-Q1 gross spread의 자체 t-stat(2.27→1.22/0.90/1.73)은 구간을 쪼개며
  낮아지는데, 이는 신호 약화가 아니라 표본(개월 수 124→75/18/31) 감소에
  따른 통계적 검정력 저하다 - 월별 cross-section 전체를 쓰는 IC가 더
  안정적인 지표이고 그쪽은 전 구간 견고했다.

## 3. 판정

**PASS** - earnings_yield는 TRAIN/VALID/TEST 분해에서 부호반전·유의성
상실 없이 통과한, 이 프로젝트 기준으로는 드물게 깨끗한 결과다. 다만:

- 이것으로 "production 채택 확정"은 아니다 - 이 프로젝트의 반복된 원칙대로
  "연구 후보 → production 결정을 실제로 고려해볼 후보"로 상향하는 근거일
  뿐(PBR-combined이 OOS 검증 통과 후 받은 것과 같은 등급).
  `factor-earnings-yield-portfolio-validation-2026-08.md`의 "즉시 운용
  가능" 문구는 이 검증 이전에 나온 것이라 과장이었다 - 이 문서로 대체한다.
- 대형주 의존(기존 robustness 문서의 발견, Large Sharpe 1.09 vs Mid/Small
  0.35)과 2022년 집중 리스크는 이 검증과 별개로 여전히 유효한 주의사항.
- 실제 포트폴리오 채택(max_positions·리밸런싱 실행)은 별도 🔴 결정 대상.

## 4. 재현

```
python research/strategy-lab/factor_earnings_yield_train_valid_test.py
```
출력: `reports/2026-09-02-earnings-yield-oos-split/earnings-yield-train-valid-test.json`
