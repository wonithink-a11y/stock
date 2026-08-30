---
track: macro
factor: vix-regime-integration
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "VIX↔regime 시차 분석 - VIX 급등(z≥+2)이 Risk-Off 신호(무조건 대비 ×3, T+1 34%)이고 평균 15거래일 후 Risk-On 전환 - 전환 타이밍 예측 축으로 고유정보"
---

# VIX ↔ Market Regime 관계 검증 — 시차 분석 (2026-08-23)

데이터: vix_daily_kr(asOf, z=직전252거래일 기준) + regime_labels + market_regime_features.
산출물: reports/2026-08-23-regime-integration-suite/integration_result.json.

## 1. VIX 급등(z≥+2)이 Risk-Off보다 먼저 나타나는가? — 예

185개 급등일 이후 라벨 분포(무조건부: Neutral 56.7% / Risk-On 31.8% / Risk-Off 11.4%):

| 시점 | Risk-On | Neutral | **Risk-Off** |
|---|---|---|---|
| T+1 | 8.6% | 38.4% | **34.1%** (무조건 대비 ×3.0) |
| T+5 | 11.9% | 40.5% | **28.6%** |
| T+10 | 11.9% | 45.9% | **23.2%** |
| T+20 | 21.1% | 45.4% | 14.6% |

급등 직후 Risk-Off 비율이 3배로 치솟았다가 20거래일에 걸쳐 무조건 수준으로 복귀한다.
(35일은 라벨 범위 밖 2014~2015분.)

## 2. 급등 후 Risk-On 전환까지 평균 몇 거래일?

급등 에피소드에서 첫 Risk-On까지: **median 15거래일 / mean 19.7 / p90 47.5**,
60거래일 내 미전환 39건(21%). → "약 3주"가 전형적 회복 소요시간.

## 3. ΔVIX와 파생변수의 시차 상관

ΔVIX(t) vs Δfeature(t+k), k=−5..+5:

| 변수 | k=−1 | k=0(동행) | k=+1 | 해석 |
|---|---|---|---|---|
| breadth | −0.088 | **−0.271** | −0.059 | 동행만 강함 |
| trend20 | −0.057 | **−0.175** | −0.069 | 동행 위주 |
| foreign flow | −0.007 | **−0.160** | +0.120 | 동행·직후 반등 흔적 |
| impl_corr20 | +0.077 | +0.071 | +0.096 | 약한 지연 정상관 |
| rvol20 | +0.056 | +0.067 | +0.087 | 낮음(아래) |

## 4. VIX는 realized volatility를 중복 측정하는가?

- **수준(level) 상관은 유의**: corr(vixLevel, rvol20)=**0.59**.
- 그러나 vixState==High 구간의 rvol20 횡단분위 평균 = **0.503**(중위권) —
  VIX 급등 국면이 한국 "실현 변동성" 상위국면과 항상 일치하지는 않는다.
- 변화량(Δ) 상관은 전 라그에서 낮다(≤0.09).
판정: VIX는 rvol20과 수준 공변하지만 **동일 변수가 아니며**, 특히 "미국 변동성
기대치"라는 정보원으로서 한국 실현변동성이 담지 않는 선행·외생 축을 제공한다.

## 5. 독립적 추가 설명력

regime_labels 자체가 vixState를 입력으로 쓰므로 "labels 대비 VIX의 증분"을 묻는
올바른 질문은 "VIX 없이 만든 regime 대비 개선 폭"이다. 본 감사 범위에서 확인된 것:
- ΔVIX의 breadth/trend 영향은 **동행 중심이고 선행(lag −1~−5) 상관은 사실상 0**이다.
- 반면 급등 이벤트의 Risk-Off 집중(T+1 34%)과 Risk-On 전환 median 15거래일은
  시차 구조로 명확히 관측됐다.
→ 결론: VIX는 "당일 국면 설명 변수"로는 rvol/breadth와 중복되지만,
**"전환 타이밍 예측 변수"(급등→평균 15거래일 내 Risk-On)**로서는 고유 정보다.

## 요약

VIX 급등은 Risk-Off의 신호이자(×3 농도), 평균 15거래일 뒤 Risk-On 전환의 시작점이었다.
breadth/trend와는 동행 상관만 있고 선행력은 없어, VIX의 연구 가치는 국면 '수준'이
아니라 '전환 타이밍' 축에 있다. 단 z-window(252일)는 첫 정의 선택값이며 이벤트 간
상관은 미보정이다.
