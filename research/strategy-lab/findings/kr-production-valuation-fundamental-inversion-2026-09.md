---
track: kr
factor: kr-production-valuation-fundamental-inversion
date: 2026-09-04
verdict: UNCLASSIFIED
criteria_version: KR-2.3
conditions: ["docs/data/history 41일·1,404건", "US10Y trailing 126거래일 국면 분류", "단일 연속 구간(regime 분산 없음)"]
reason: "valuation·fundamental 축 IC가 최근 41일 실제 운영 데이터에서 역방향(-0.191·-0.139) - 기술축(MA크로스, 오늘 KR-2.3로 수정)과 달리 아직 원인 미확정. 국면(미국 10년물 상승) 가설은 검증해봤으나 오히려 기각 방향 - 이 구간 자체가 US10Y rising 하나뿐이라 falling과 비교가 안 됨"
---
# 운영 채점(KR-2.3) — valuation·fundamental 축 최근 41일 역방향 (2026-09-04)

배경: 사용자가 대시보드 백테스트 탭(`docs/data/backtest-v2.json`)에서 "A등급
승률 0%·마이너스, 등급 낮을수록 이익률 높음"을 재차 보고. `docs/data/history/`가
그 사이 41일(07-12~09-03)까지 쌓여 그 실제 데이터로 재확인했다 -
`scripts/backtest-report.js`가 저장된 옛 점수가 아니라 **매번 현재
criteria(오늘 승격한 KR-2.3 포함)로 원본 stockData를 다시 채점**한다는 걸
코드로 확인(`lib/backtester.js` → `scoreStock()` + `loadCriteria()`) -
즉 이번 결과는 이미 KR-2.3(MA크로스 반전) 적용 후다.

---

## 1. 결론 요약

**MA크로스 수정(오늘 KR-2.3)은 실제로 효과가 있었다** - technical 축 IC가
거의 0으로 평평해졌다. **그러나 valuation·fundamental 두 축이 여전히
강하게 역방향**이라 전체 점수(total)도 여전히 역방향이다. 미국 10년물
국면 가설로 설명해보려 했으나 **오히려 기각 방향**(이 구간 전체가 "국면상
가치주에 유리해야 할" rising 하나뿐인데도 valuation이 역방향).

## 2. 축별 IC (d20, 41일·1,404건, KR-2.3 적용)

| 축 | n | IC | 방향 |
|---|---:|---:|---|
| fundamental | 1,404 | -0.139 | 역방향 |
| **valuation** | 1,470 | **-0.191** | **역방향(최대)** |
| technical | 1,484 | +0.011 | 정상(≈0, 오늘 수정 효과) |
| supplyDemand | 1,484 | -0.023 | 노이즈 수준 |
| total | 1,484 | -0.206 | 역방향 |

등급별(A~E, docs/data/backtest-v2.json 재실행 결과)도 완전히 단조 역전:

| 등급 | n | 평균수익률 | 승률 |
|---|---:|---:|---:|
| A | 7 | -9.74% | 0% |
| B | 322 | +2.84% | 58.7% |
| C | 597 | +6.71% | 63.1% |
| D | 336 | +6.70% | 67.0% |
| E | 142 | +14.82% | 86.6% |

재현: `node research/strategy-lab/probe-kr-score-axis-ic-2026-09.js`

## 3. 미국 10년물 국면 가설 — 검증 시도, 기각 방향

이 프로젝트의 기존 PBR 매크로 연구(`pbr-macro-rate-regime-check-2026-08.md`)
결론은 "미국 10년물 상승기(trailing 126거래일 상승) = 가치주에 유리한 국면"
이었다. 같은 정의(TRAIL_DAYS=126, 재최적화 없음)를 그대로 재사용해 이 41일
구간을 분류했다.

```
41일 전체가 US10Y rising 국면 하나뿐 (falling 구간 자체가 없음, n=0)
US10Y rising 국면 valuation IC = -0.191
```

**"유리해야 할" 국면 안에 있는데도 역방향** - 국면 가설로 이 현상을 설명할
수 없다. 비교 대상(falling 구간)이 이 41일 안에 아예 없어 이 스크립트
자체로는 가설을 완전히 기각하지도, 확정하지도 못한다(§5 한계 참고).

재현: `node research/strategy-lab/probe-kr-valuation-macro-regime-2026-09.js`

## 4. 관측된 대안 가설 — 코스피 급등장(미검증)

같은 41일 구간 `ui/data/macro.json`의 KOSPI 수준을 보면 이 구간 동안
**+22.06% 상승**(대시보드 매크로 탭 실측, 2026-08-28 기준 시계열). 급등장은
전형적으로 저평가(가치)보다 이미 오르고 있는 종목(모멘텀·성장)이 계속
이기는 구간이라, valuation·fundamental 축 저평가 스크리닝이 오히려
발목을 잡는 패턴과 방향이 맞아떨어진다. **단, 이 문서 시점까지 정식으로
검증한 적 없다** - 매크로 데이터로 뒷받침되는 그럴듯한 가설일 뿐이다.

## 5. 이번 조사의 한계 (정직하게 밝힌다)

- **단일 연속 구간이다.** 41일(07-12~09-03)은 하나의 시장 국면(코스피
  급등장 + US10Y rising) 안에 전부 들어간다 - 독립적인 여러 창이 아니라
  "사건 하나"로 봐야 한다(이 프로젝트가 반복 지적해 온 함정, 예:
  2026-09-02 세션의 37일 창 조사와 같은 종류의 제약).
- US10Y rising/falling 비교가 원리적으로 불가능했다(이 구간에 falling이
  없음) - 가설을 제대로 검증하려면 더 긴 이력이 필요하다(§6).
- 코스피 급등장 가설은 상관 관측일 뿐 인과 검증이 아니다.
- `docs/data/history`의 원본 stockData 자체가 PIT(point-in-time) 보증이
  없다(운영 파이프라인 그대로 수집된 것) - 이 진단은 그 위에서 돈다.

## 6. 정식 검증 방법 (다음 단계 제안, 미실행)

이번 41일은 표본이 너무 작고 국면이 하나뿐이라 결론을 못 낸다. 제대로
가르려면:

1. **더 긴/다른 소스로 국면 다양성 확보** - `docs/data/history`(41일)
   대신 이미 완성된 `data/backfill/scores/`(A5 10년 백필, 2016~2026,
   1,254,759행, 오늘 KR-2.3로 재백필 완료)를 쓴다. 이쪽은 US10Y
   rising/falling 둘 다 충분한 표본(§`pbr_macro_rate_regime_check.py`가
   이미 65개월 대 57개월로 나눈 전례가 있음)이 있어 이 문서가 못 한
   비교를 할 수 있다.
2. **코스피 급등장 가설은 정식 regime classifier로 만들어 검증** -
   trailing 3개월 또는 6개월 KOSPI 수익률을 US10Y와 같은 방식(사전 고정
   창, 재최적화 없음)으로 분류해 valuation 축 IC를 momentum구간 vs
   비momentum구간으로 나눈다. `ui/data/macro.json`의 krKospi 시계열을
   그대로 쓸 수 있다.
3. **Newey-West 보정** - 월별/주별 스냅샷은 자기상관이 있다(이 프로젝트
   표준, `4*(n/100)^(2/9)` 자동 lag). naive t는 부풀려진다.
4. **연도별 breakdown을 반드시 같이 낸다** - PBR 2022년 집중 사례처럼
   "1~2년이 전체를 설명"하는 함정을 피한다.
5. **TRAIN에서 국면 정의·창 길이를 고정한 뒤 VALID·TEST에서만 확인** -
   사후에 가장 잘 맞는 창을 고르지 않는다(이 프로젝트 표준 절차).
6. 만약 코스피 모멘텀 국면이 진짜 원인으로 확인되면, 그 다음 질문은
   "타이밍 필터로 쓸 수 있는가"인데 - 이 프로젝트가 PBR·TREND-BREAKOUT·
   5DC·LOWMOM60·combined 다섯 번 반복 검증한 교훈("상관관계 ≠ 타이밍
   가치", 순수 노출 오버레이 + 상수노출 대조군 방법론)을 그대로 적용해야
   한다 - 상관만 보고 바로 규칙화하지 않는다.

## 검증 가능한 근거 목록

- `research/strategy-lab/probe-kr-score-axis-ic-2026-09.js` - 재실행하면
  동일 결과(런타임 수 초, `docs/data/history/` 41개 파일 읽음)
- `research/strategy-lab/probe-kr-valuation-macro-regime-2026-09.js` -
  국면 분류 재현
- `docs/data/backtest-v2.json` - `node scripts/backtest-report.js` 재실행
  결과(등급별 표)
- `ui/data/macro.json` - `series.usTreasury10y.history`·`series.krKospi.history`
