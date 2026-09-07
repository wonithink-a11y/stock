---
track: kr
factor: factor-earnings-yield-selection-refresh-recheck
date: 2026-09-08
verdict: HOLD
criteria_version: v1
conditions: ["factor_earnings_yield_mtm_reverification.py 무변경 재실행(출력 디렉터리 날짜화 한 줄만 수정)", "policy.json maxPositions=30 복구 후 실행(커밋 41a5732)", "기간 2016-01-01 ~ 2026-08-14 — 스크립트 하드코딩, 08-30 실행과 동일 창", "MTM 월별 시가평가(pbr_vs_ew_monthly_mtm.py 함수 재사용), exit_date 실현손익 회계 아님", "비교 기준선 = reports/2026-08-30-factor-earnings-yield-mtm-reverification/(로컬 유일본, 덮어쓰지 않고 보존)"]
reason: >-
  실험실이 보고한 "selection 갱신으로 earnings_yield 가 CAGR 4.68% -> 1.98%,
  n 567 -> 1355 로 붕괴" 는 **재현되지 않는다.** mp=30 을 복구하고 정밀 MTM 으로
  다시 재니 CAGR 4.86% -> 4.80%, Sharpe 0.483 -> 0.469, MDD -15.48% -> -15.78%
  로 사실상 무변화다. 그 붕괴는 selection 갱신의 효과가 아니라 (a) 같은 기간
  살아 있던 maxPositions 200 드리프트와 (b) 실현손익(exit_date) 회계가 겹친
  산물이었다. 같은 이유로 실험실이 보고한 "rev1m 이 -0.88 -> +1.83 으로 부호
  반전" 도 재현되지 않는다 — MTM mp=30 에서는 -0.91% -> -1.30% 로 여전히 음이다.
  따라서 08-30 MTM 재확인 문서의 수치는 갱신 대상이 아니라 **그대로 유효**하고,
  부모 판정(HOLD)도 바뀌지 않는다. 다만 EW 벤치마크가 3.04% -> 2.30% 로 떨어져
  EY 의 겉보기 초과(2.50%p)가 부풀었다 — market-benchmark-comparison-2026-09 가
  지목한 하향편향 EW 가 바로 이 2.30% 이고, 편향보정 EW(약 4.37%) 대비로는
  0.4%p 대다. capacity 순위는 mp=30 과 50 이 뒤바뀌었으나(4.80 vs 5.10) 08-30
  이 이미 "사실상 동률" 로 적은 자리라 재선택하지 않는다.
cagr: 4.80
sharpe: 0.4692
mdd: -15.78
n: null            # 산출물이 월 수를 안 남긴다(연도 11개만). 계산해 채우지 않는다 - 교훈57
t_stat: null       # 이 스크립트는 초과수익 t 를 내지 않는다
stats:
  compare_2026_08_30_to_2026_09_08:
    ew_benchmark_liquid_v1: {cagr: [3.04, 2.30], sharpe: [0.2876, 0.2303], mdd: [-22.61, -25.72]}
    factor_earnings_yield_v1: {cagr: [4.86, 4.80], sharpe: [0.4834, 0.4692], mdd: [-15.48, -15.78]}
    factor_rv60_v1: {cagr: [2.42, 2.68], sharpe: [0.3351, 0.3630], mdd: [-19.77, -19.82]}
    factor_rev1m_v1: {cagr: [-0.91, -1.30], sharpe: [0.0031, -0.0212], mdd: [-36.73, -41.79]}
    composite_ey_rv60_equal_weight: {cagr: [-7.96, -8.63], sharpe: [-0.4311, -0.4582], mdd: [-59.09, -63.43]}
    composite_ey_rv60_rank_composite: {cagr: [4.50, 4.55], sharpe: [0.5231, 0.5287], mdd: [-17.25, -17.24]}
  capacity_2026_09_08: {mp20: {cagr: 4.11, sharpe: 0.4195, mdd: -16.61}, mp30: {cagr: 4.80, sharpe: 0.4692, mdd: -15.78}, mp50: {cagr: 5.10, sharpe: 0.4994, mdd: -15.84}, mp100: {cagr: 3.31, sharpe: 0.4162, mdd: -13.13}}
  selectionVersions:
    factor_earnings_yield_v1: {sha256: "02da62f9db65", period: "2016-01-01~2026-09-03", avgPerMonth: 67.3}
    factor_rv60_v1: {sha256: "9cd544b87a05", period: "2016-01-01~2026-09-03", avgPerMonth: 185.2}
    factor_rev1m_v1: {sha256: "b301b7f2070c", period: "2016-01-01~2026-09-03", avgPerMonth: 185.4}
    composite_ey_rv60_equal_weight: {sha256: "e868448ea9c6", period: "2016-01-01~2026-08-14"}
    composite_ey_rv60_rank_composite: {sha256: "3474c051e210", period: "2016-01-01~2026-08-14"}
---

# earnings_yield — selection 갱신 후 수치 재확인 (2026-09-08)

`keep-paper-candidate-final-verification-2026-09.md` §5-1 이 "selection 갱신 후
earnings_yield 성과 수치를 findings 에 갱신(버전 명시) → Claude 담당" 으로
남긴 항목의 처리 결과다.

**결론부터: 갱신할 수치가 없다.** 실험실이 관측한 변화가 selection 갱신 때문이
아니었다.

## 1. 무엇을 다시 쟀나

실험실의 재현은 `run_factor_backtest.py` 로 돌았다. 그 스크립트의
`compute_metrics_fast()` 는 **exit_date 기준 실현손익**으로 월별 손익을 쌓고
거기서 Sharpe·MDD 를 낸다 — CLAUDE.md 함정 (5)가 지목한, 2026-08-22 에 폐기된
회계다. 게다가 그 시점 `policy.json` 은 `maxPositions=200` 드리프트 상태였다
(커밋 `bcb3c8a`, 2026-09-04 → 복구 `41a5732`, 2026-09-07).

그래서 실험실 숫자를 옮기지 않고, **이미 있던 정밀 MTM 스크립트**
(`factor_earnings_yield_mtm_reverification.py`)를 mp=30 복구 상태에서 다시
돌렸다. 08-30 실행과 **같은 스크립트·같은 기간창(2016-01-01~2026-08-14)** 이라
차이는 그 사이 갱신된 selection·상류 패널·가격뿐이다.

★ 이 스크립트는 출력 디렉터리를 `2026-08-30-...` 로 하드코딩하고 있어서 그대로
돌리면 비교 기준선(로컬 유일본, gitignore 대상)을 덮어썼다. 실행일 기준으로
갈리게 한 줄 고친 뒤 실행했다.

## 2. 결과 — EY 는 사실상 그대로다

| 전략 | CAGR 08-30 → 09-08 | Sharpe | MDD |
|---|---|---|---|
| **factor_earnings_yield_v1 (mp=30)** | **4.86% → 4.80%** | 0.483 → 0.469 | -15.48% → -15.78% |
| ew_benchmark_liquid_v1 | 3.04% → **2.30%** | 0.288 → 0.230 | -22.61% → -25.72% |
| factor_rv60_v1 | 2.42% → 2.68% | 0.335 → 0.363 | -19.77% → -19.82% |
| factor_rev1m_v1 | -0.91% → **-1.30%** | 0.003 → -0.021 | -36.73% → -41.79% |
| composite (equal_weight) | -7.96% → -8.63% | -0.431 → -0.458 | -59.09% → -63.43% |
| composite (rank_composite) | 4.50% → 4.55% | 0.523 → 0.529 | -17.25% → -17.24% |

실험실이 보고한 두 가지가 **둘 다 재현되지 않는다.**

- "EY CAGR 4.68% → 1.98%, MDD -9.9% → -4.97%" → MTM mp=30 에서는 4.86% → 4.80%.
- "rev1m 이 -0.88 → +1.83 으로 부호 반전" → MTM mp=30 에서는 -0.91% → -1.30%,
  **여전히 음수**다.

둘 다 mp=200(67종 decile 을 30종으로 자르던 것을 전부 담게 됨) + 실현손익 회계의
산물로 본다. 실험실이 원인을 selection 갱신으로 적은 것은 그 시점에 드리프트를
몰랐기 때문이고, 잘못 본 것을 탓할 자리가 아니다 — 드리프트가 커밋 메시지에
없었다.

## 3. 그래도 바뀐 것 — EW 벤치마크가 내려갔다

`ew_benchmark_liquid_v1` 이 3.04% → **2.30%** 로 떨어졌다. 이 2.30% 는
`market-benchmark-comparison-2026-09.md` §2 가 "하향편향" 으로 지목한 바로 그
수치다(maxPositions=1500 인데 월평균 적격이 1,029개라 현금이 놀고, 슬롯예산
66,667원보다 비싼 종목을 못 산다).

그래서 EY 의 겉보기 초과 **2.50%p**(4.80 − 2.30)를 알파로 읽으면 안 된다.
같은 문서가 계산한 편향보정 EW(현금제약만 제거, CAGR 4.37%) 대비로는 **0.4%p
대**이고, 이는 "편향보정 EW 를 이긴 전략 0/8" 결론과 일관된다.

## 4. capacity 순위가 뒤바뀌었다 — 재선택하지 않는다

```
        08-30              09-08
mp=20   4.00% / 0.413      4.11% / 0.420
mp=30   4.86% / 0.483  ←   4.80% / 0.469
mp=50   4.74% / 0.471      5.10% / 0.499  ←
mp=100  3.03% / 0.385      3.31% / 0.416
```

08-30 문서가 이미 "capacity-test 의 'mp=50이 최선' 결론도 MTM 에서는 mp=30 과
사실상 동률(0.483 vs 0.471)" 이라고 적었다. 지금은 방향만 반대로 같은 크기의
차이다. **데이터가 조금 갱신될 때마다 1위가 오가는 것은 그 둘이 구분되지
않는다는 뜻이지 mp=50 이 낫다는 뜻이 아니다.** 이 저장소가 반복해서 데인
패턴이라(`pbr-topn-strength-oos` 의 TRAIN→VALID 순위 완전 역전,
`pbr-roe-quality-overlay-oos` 의 gate50) 사후 재선택하지 않고 mp=30 을 유지한다.

## 5. 버전 명시 (실험실이 요구한 항목)

```
factor_earnings_yield_v1   selection sha256=02da62f9db65  2016-01-01~2026-09-03  67.3종/월
factor_rv60_v1                       sha256=9cd544b87a05  2016-01-01~2026-09-03  185.2
factor_rev1m_v1                      sha256=b301b7f2070c  2016-01-01~2026-09-03  185.4
composite_ey_rv60_equal_weight       sha256=e868448ea9c6  2016-01-01~2026-08-14
composite_ey_rv60_rank_composite     sha256=3474c051e210  2016-01-01~2026-08-14
policy   maxPositions=30 (커밋 41a5732 로 복구)
기간창   2016-01-01 ~ 2026-08-14 (스크립트 하드코딩, 08-30 과 동일)
```

두 가지를 함께 남긴다.

1. **selection 갱신 커밋 `12e01f2` 는 리프레시가 아니라 버그 수정이다** —
   "마지막 리밸런싱월이 fwd1m 필터에 걸려 빠지던 것 수정". 즉 갱신 후 수치가
   갱신 전보다 **맞는 쪽**이다.
2. **복합 2종은 리프레시되지 않았다**(period 가 2026-08-14 에 멈춤). 단일 팩터
   셋만 갱신됐다. 위 표에서 composite 행을 단일 팩터 행과 나란히 읽을 때
   이 비대칭을 감안한다. 다만 이 백테스트의 기간창 자체가 2026-08-14 에서
   끝나므로 이번 수치 비교에는 영향이 없다.

## 6. 판정

부모 문서(`factor-earnings-yield-mtm-reverification-2026-08.md`, HOLD)의 수치는
**갱신 대상이 아니며 그대로 유효**하다. 판정도 HOLD 유지다. 이 문서는 그 사실을
확인한 관측치이고, 실험실 §5-1 항목은 이것으로 종결한다.

산출물: `reports/2026-09-08-factor-earnings-yield-mtm-reverification/`
(기준선 `reports/2026-08-30-.../` 는 보존됨).
