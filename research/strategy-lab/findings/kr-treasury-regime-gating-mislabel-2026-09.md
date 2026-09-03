---
track: kr
factor: treasuryRatio
subproject: kr-treasury-regime-2026-08 (후속 검증)
date: 2026-09-02
verdict: STEP 20-26 전체 재해석 필요 — "Treasury_Top20" 이름과 실제 구성이 다름
criteria_version: regime-gating-decomp-v1
conditions: [Treasury_Top20 strategy construction, TRAIN/VALID/TEST, w_treas gated by regime=='Risk-On']
reason: >-
  kr_treasury_incremental_step1.py를 포함해 Step 20-26 전체가 공유하는
  "Treasury_Top20" 전략은 이름과 달리 Risk-On 구간에서만 TreasuryRatio
  선택을 쓰고 Neutral/Risk-Off 구간(TRAIN 58%, VALID 71%, TEST 68%)에는
  LOWMOM60으로 조용히 대체한다. 실제 분리 측정 결과 Treasury 슬리브가
  활성화된 달의 평균 수익률은 TRAIN +0.03%(연율), VALID -6.94%, TEST
  -4.30%로 3구간 전부 0 이하다 - 보고된 CAGR(13.80%/18.89%/10.21%)은
  사실상 전부 LOWMOM60 대체분(연율 24.89%/31.67%/17.88%)에서 나온 것.
  Step 20-26의 "Treasury cutoff/weighting 민감도" 결론들은 이 오염된
  베이스 위에서 나온 것이라 재해석이 필요하다.
---

# TreasuryRatio 포트폴리오 실험(Step 20-26) — "Treasury_Top20"이 실은 대부분 LOWMOM60였다

## 0. 배경

사용자 요청으로 Step 20~26(LowVol 결합·연속가중·레짐가중·비용강건성·
포트폴리오 incremental·cutoff 민감도)의 실제 숫자를 검증하다가, 그 실험들이
공통으로 쓰는 "Treasury_Top20" 전략의 실제 구현을 소스에서 직접 확인했다.

## 1. 발견 — 소스 코드

`kr_treasury_incremental_step1.py` (및 step2a/2b/3a/3b/4a/4b,
`kr_treasury_cost_robust.py`, `kr_treasury_rank_weight.py` 등 Step 20-26
전체가 이 패턴을 공유):

```python
elif strategy_name == "Treasury_Top20":
    w_treas = 1.0 if regime == "Risk-On" else 0.0
    w_lowmom = 1.0 - w_treas
```

즉 "Treasury_Top20"은 Risk-On 구간에서만 TreasuryRatio 상위 20%를 사고,
**Neutral/Risk-Off 구간에는 LOWMOM60(저모멘텀60) 슬리브로 조용히 대체한다.**
이름만 보면 순수 Treasury 전략처럼 보이지만 실제로는 레짐 조건부 혼합
전략이다 - 이 사실이 어느 findings.md에도 명시돼 있지 않았다.

## 2. 분리 측정

원본과 동일한 로직(계측만 추가)으로 재실행해, 매달 실제로 어느 슬리브가
쓰였는지 태그하고 각각의 기여를 분리했다. 스크립트:
`kr_treasury_regime_decomp_check.py`

| 구간 | 보고된 CAGR | Risk-On 비중 | **Treasury슬리브 단독**(항상 켜졌다면 연율) | **LOWMOM60 대체분 단독**(항상 켜졌다면 연율) |
|---|---:|---:|---:|---:|
| TRAIN | 13.80% | 41.9%(31/74개월) | **+0.03%** | **+24.89%** |
| VALID | 18.89% | 29.4%(5/17개월) | **-6.94%** | **+31.67%** |
| TEST | 10.21% | 32.3%(10/31개월) | **-4.30%** | **+17.88%** |

## 3. 해석

**3개 구간 전부, Treasury 슬리브가 실제로 켜진 달의 평균 수익률은 0 이하다
(TRAIN 거의 0%, VALID·TEST는 마이너스).** 보고된 CAGR의 사실상 전부가
LOWMOM60 대체분(연율 18~32%)에서 나왔다. "Treasury_Top20 CAGR 13.80%"라는
숫자는 TreasuryRatio가 잘 골랐다는 증거가 아니라 **LOWMOM60이 잘 작동했다는
증거를 다른 이름으로 보고한 것**에 가깝다.

이건 이전 검증(Newey-West 재계산, 연도별 분해)에서 확인한 "TEST 구간의
Q5-Q1 스프레드는 자기상관 보정 후에도 견고하다"는 결론과 **모순되지
않는다** - 그건 상대적 순위(Q5가 Q1보다 낫다)를 본 것이고, 이건 Q5의
**절대 수익률**이 다른 전략(LOWMOM60)보다 못하다는 별개의 질문이다.
즉 TreasuryRatio가 "종목을 상대적으로 잘 가르는 신호"일 수는 있어도,
"그 자체로 투자할 만한 절대수익을 내는 전략"은 전혀 아니라는 뜻 -
두 질문이 다르다는 걸 이번에 분리해서 확인했다.

## 4. Step 20-26 전체에 대한 영향

Step 20(LowVol 결합)·21(연속가중)·22(레짐가중)·23(비용강건성)·
24-3(incremental)·24-4(cutoff 민감도) 전부가 이 "Treasury_Top20"(또는
그 변형)을 베이스로 비교했다. 즉:

- "Top10이 Top20보다 +0.55%p 낫다"·"LowVol 결합이 0.2~1.2%p 악화시킨다"
  같은 **cutoff/weighting 간 상대 비교는 여전히 유효할 수 있다**(같은
  오염을 공유하는 것끼리의 비교이므로).
- 하지만 "TreasuryRatio 전략이 LOWMOM60만 쓰는 것보다 낫다"거나 "Treasury
  선택이 incremental alpha를 더한다"는 절대적 주장은 **이 데이터로는
  지지되지 않는다** - LOWMOM_Treasury_High50이 Treasury_Top20보다 근소하게
  나은 것(+0.27%p, 원본 문서 Step 24-3)도 두 전략 다 LOWMOM60이 대부분을
  차지하는 구조라 애초에 큰 차이가 나기 어려운 비교였다.

## 5. 종합 판단

TreasuryRatio를 **"레짐 필터로 켰다 껐다 하며 LOWMOM60에 얹는 전략"**으로
포장한 Step 20-26의 포트폴리오 결과는 재해석이 필요하다 - 이번 데이터로는
Treasury 슬리브 자체가 절대수익에 기여한 바가 없다(오히려 VALID·TEST는
마이너스). Step 19/24-1/24-2/27/28(레짐 게이팅 없는 순수 cross-sectional
Q1-Q5 테스트)은 이 문제와 무관하며 그 결과(TEST에서 견고한 IC)는 유효하다.

**다음에 이 라인을 다시 열려면**: "Treasury Top20을 Risk-On에서만 쓰고
나머지는 LOWMOM60로 채운다"가 아니라, **Treasury 슬리브 자체를 레짐과
무관하게 상시 가동한 순수 포트폴리오**로 다시 측정해야 "Treasury가 정말
투자할 만한 절대수익을 내는가"에 답할 수 있다(이번 검증 범위 밖).

## 6. 재현

```
python research/strategy-lab/kr_treasury_regime_decomp_check.py
```
출력: `reports/2026-09-02-kr-treasury-regime-decomp/kr-treasury-regime-decomp-results.json`
