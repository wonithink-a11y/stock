# A6 v1 — exitReasonCoverage + GATE-EP-1/2 진단 (2026-08-24)

이 리포트는 `scripts/build-a6-coverage-report.js`가 계산한다. **Primary 결론
(IC·분위 스프레드 확정 해석)은 포함하지 않는다** — GATE 통과 여부와 무관하게
아직 계산하지 않는다(exitPrice 미수집이 별도로 막고 있다, 아래 참고).

overlay 상태: **EO 미승격** — A1b baked 값(전건 UNKNOWN)만 사용했다. exit-overlay.yml을 먼저 트리거하라.

## exitReasonCoverage (A1b DELISTED corp 전체 1223건 기준)

| exitReason | count | share |
|---|---|---|
| UNKNOWN | 1223 | 100.0% |

## GATE-EP-1

```
UNKNOWN 1223 / 1223 = 100.0%   (임계 5%)
판정: FAIL → A6 Primary 결론 금지 (HOLD)
```

## GATE-EP-2 (A5에 DELISTED 행이 있는 461종목 대상, 폐지 직전 최종 finalScore 5분위)

| 분위 | corp 수 | UNKNOWN | UNKNOWN율 | finalScore 범위 |
|---|---|---|---|---|
| Q1 | 92 | 92 | 100.0% | 9.2 ~ 35.0 |
| Q2 | 92 | 92 | 100.0% | 35.0 ~ 40.3 |
| Q3 | 92 | 92 | 100.0% | 40.3 ~ 44.5 |
| Q4 | 92 | 92 | 100.0% | 44.5 ~ 53.5 |
| Q5 | 93 | 93 | 100.0% | 53.7 ~ 91.8 |

```
Q5/Q1 비 = 1.00   (임계 3.0)
판정: PASS
```

## 종합 판정

```
HOLD — A6 Primary 결론 금지. 진단 산출물(이 리포트)만 유효하다.
```

exitPrice(정리매매 최종가·공개매수가) 수집 파이프라인은 이 프로젝트 어디에도
없다 — GATE를 통과해도 liquidation/tender 모드의 EP-1.0 실현수익률 계산은
그 데이터 없이는 불가능하다(별도 🔴 결정, 이번 범위 밖).
