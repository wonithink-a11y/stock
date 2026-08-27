# DD252 후속 — 유니버스 게이트가 LOWMOM60/REV20 alpha를 보존하는가

- 연구일: 2026-08-26
- 스크립트: `research/strategy-lab/universe_gate_validation_study.py`
- 원본 결과: `research/strategy-lab/reports/2026-08-26-universe-gate/gate-results.json`
- 성격: **factor-level 선행 검증**. DD252 portfolio 자체의 백테스트가 아니다.
  Production 정책 승격 아님 — 연구 후보 기록.

## 1. 목적

DD252 실행가능성 제약(유동성·변동성·가격) 후보를 정하기 전에, 그 제약들이
LOWMOM60(`mom60`)·REV20(`mom20`) 두 기존 역전 신호의 alpha를 얼마나
보존/훼손하는지 factor 단계에서 먼저 확인했다.

| Arm | 조건 | 표본 보존율 | 월평균 종목수 |
|---|---|---:|---:|
| A_full | 전체 유니버스 | 100% | 2,061.5 |
| B_liq1e8 | 거래대금(20세션 평균) ≥ 1억원 | 89.1% | 1,836.8 |
| C | B + rv20 상위 decile(날짜별 전체 횡단면 기준) 제외 | 79.5% | 1,639.0 |
| D | C + 종가 ≥ 5,000원 | 54.3% | 1,120.2 |

## 2. 결과

### B — 유동성 필터만

| | LOWMOM60 d60 | REV20 d60 |
|---|---|---|
| spread A→B | +1.84%→+1.63% | +2.13%→+1.96% |
| NW-t A→B | 1.91→1.68 | 2.63→2.44 |

표본 11% 감소에도 spread·유의성 대부분 보존. **유효한 후보.**

### C — 극단 고변동 제외 추가

| | LOWMOM60 | REV20 |
|---|---|---|
| d60 spread | +1.84%→**-0.15%** | +2.13%→**-0.27%** |
| d120 spread | +0.58%→**-2.78%** | +1.01%→**-2.25%** |

d60에서 부호가 반전된다. rv20 상위 decile에 역전 alpha가 집중돼 있을 가능성 —
"고변동=위험이므로 제거"라는 통상 가정이 이 팩터군에서는 alpha 자체를
제거할 수 있다. **현재 DD252에 적용하지 않는다.**

### D — 가격 필터 추가

- 표본 보존율 54.3%, LOWMOM60 d60 spread -1.36%, REV20 d60 spread -0.79%
- Net@30bps d20: LOWMOM60 -0.03%, REV20 약 0%(-0.00%)

저가주 alpha를 상당 부분 제거한다. **현재 적용하지 않는다.**

### 부가 관찰

- A→D 바스켓 겹침률(d60): LOWMOM60 51.96%, REV20 51.55% — 강한 게이트를
  적용하면 원 신호의 절반 정도만 남는다.
- C·D에서 최근 연도(2024~2026)의 IC 부호가 양전하는 빈도가 늘어 —
  표본 축소뿐 아니라 factor의 시간적 성격 자체가 달라질 가능성이 있다.

## 3. DD252와의 연결 — 아직 열려있는 질문

이 연구는 **factor-level**이지 DD252 portfolio 백테스트가 아니다. B의
유효성이 DD252 CAGR·Sharpe 개선으로 이어진다고 가정하지 않는다. 실제
DD252 구현에는 top-30·120세션 TIME_EXIT·동일종목 단일포지션·staggered
cohort 근사가 있어, factor-level 결과와 portfolio-level 결과가 다를 수
있다. 차이가 나타나면 다음을 구분해서 본다(자동 폐기 금지):
factor-level alpha / portfolio construction effect / universe composition
effect / liquidity constraint effect / position-cap·overlap effect /
holding-period effect.

## 4. 현재 판단

- 거래대금 ≥ 1억원 — DD252 실행가능성 제약의 유력한 후보
- 극단 고변동 제외 — 현재 적용하지 않음(alpha 훼손 증거)
- 가격 ≥ 5,000원 — 현재 적용하지 않음(alpha 훼손 증거)

최종 판단은 DD252의 portfolio-level full backtest에서 확인한다.

## 5. Claude 독립검증 (2026-08-27)

인용된 수치(retention·spread·NW-t·overlap 등 20개 이상) 전부 원본
`gate-results.json`과 소수점까지 일치 확인. 스크립트(`universe_gate_
validation_study.py`)도 대조 — `liquidity_factor_study.py`의 기검증
헬퍼(`newey_west_t`·`daily_ic_series`·`monthly_rebalance_dates`)를
재사용해 새 통계 버그 위험이 낮고, PIT 절단(feature는 t까지, forward
return은 t+h)과 look-ahead 없음을 코드로 확인. forward return을 A4
패널과 독립 재계산해 대조하는 무결성 체크(`forwardReturnIntegrityRecheckVsParquet`,
match rate 98.3~99.7%)도 포함돼 있어 데이터 정합성도 자체 검증됨.
방법론상 문제 발견 못 함 — 판정("B 유력, C/D 보류")을 그대로 신뢰할 만하다.
