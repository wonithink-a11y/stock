---
track: kr
factor: pbr-exposure-overlay-vs-ranking-cut
date: 2026-08-24
verdict: REJECT
criteria_version: backfill-v1
conditions: ["us_treasury10y_chg6m", "exposure_frac", "ranking_cut_control"]
reason: "랭킹컷 개선은 노출 타이밍이 아니라 '더 타이트한 저PBR 스크리닝' 구성효과 재확인 - 노출 고정 시 CAGR 4.72→2.65·Sharpe 0.4556→0.3976 열위, 이진·연속 사이징 경로 폐쇄"
cagr: 2.65
sharpe: 0.3976
mdd: -12.35
---
# PBR 비중조절 — 노출효과 vs 구성효과 분리 (2026-08-24)

`pbr-sizing-macro-continuous-2026-08.md`(매달 top-K PBR 랭킹 컷)의 개선분이
진짜 "미국10Y 타이밍" 덕인지, 아니면 컷하는 과정에서 저PBR 종목만 더 깊이
남겨서 생긴 "구성 효과"인지 분리해달라는 사용자 요청. **결론: 거의 전부
구성 효과였다** — 구성을 baseline과 100% 동일하게 고정하고 노출만 조절하면
개선은커녕 CAGR·Sharpe 둘 다 baseline보다 나빠진다.

이 세션은 커밋/푸시하지 않음(사용자 지시) — 로컬 파일로만 남긴다.

---

## 1. 두 메커니즘

| | 랭킹컷 sizing (기존, 08-23) | 노출 오버레이 (신규, 08-24) |
|---|---|---|
| 구성(어떤 종목을 들고 있나) | **exposure_frac에 따라 매달 top-K 컷** (K=round(30*frac), PBR 오름차순 상위만) | **baseline과 완전 동일**(30종목 그대로) |
| 비중 조절 방법 | selection.json 자체를 줄임(engine이 자동으로 빈 슬롯=현금 처리) | baseline의 실제 월간 수익률 r(t)에 exposure_frac(t)를 곱한 오버레이 |
| 엔진 변경 | 없음(engine 무변경, selection.json만 신규) | 없음(engine 무변경, 이미 계산된 equity curve의 순수 후처리) |
| exposure_frac 정의 | 동일(usTreasury10yChg6m trailing 126거래일, p10/p90 전체표본 정규화) — `build_pbr_sizing_selection.py`의 `exposure_lookup()`을 그대로 import해 재사용, 두 방법이 **완전히 같은 축·같은 임계값**을 씀 |

오버레이 공식: `equity(t) = equity(t-1) * (1 + exposure_frac(t-1시점) * r_baseline(t))` —
구간 시작 시점(전월말)의 정보로만 그 구간 노출을 정한다(PIT), 미래 수익률을
보고 그 달 노출을 정하지 않는다.

## 2. 결과 — 구성을 고정하면 개선이 사라진다

| | CAGR | MDD | Sharpe | Calmar | 평균 노출 |
|---|---|---|---|---|---|
| baseline(pbr_value_v1) | **+4.72%** | -21.70% | **0.4556** | 0.2175 | 100% |
| 랭킹컷 sizing (구성+노출 혼재) | +4.43% | -17.49% | 0.4603 | **0.2533** | 47.5%(entry 기준) |
| **노출 오버레이(구성 동일)** | **+2.65%** | -12.35% | **0.3976** | 0.2146 | 46.8% |

**평균 노출은 두 메커니즘이 거의 같다(47.5% vs 46.8%)** — 그런데 성과는
크게 다르다(CAGR 차이 +1.78%p, Sharpe 차이 +0.0627, 전부 랭킹컷 쪽이 우세).
같은 축·같은 임계값·거의 같은 평균 노출로 이 정도 차이가 난다는 것 자체가
**랭킹컷 버전의 개선분이 "노출을 언제 줄였나"가 아니라 "무엇을 남겼나"에서
왔다는 직접적인 증거**다.

## 3. 왜 다른가 — 구성 효과의 정체

랭킹컷은 노출을 줄일 때 **항상 그 달의 PBR 순위가 가장 나쁜 종목부터
뺀다** — exposure_frac이 낮을수록 남는 건 "가장 저PBR인(팩터 강도가 가장
센) 소수 종목"뿐이다. 이 프로젝트가 이미 확인해 둔 사실(decile IC t=6.30,
저PBR일수록 단조적으로 좋음 - 2026-08-21 검증)과 겹치면, **노출이 낮은
달일수록 우연히 "더 순수한 저PBR 포트폴리오"가 되고, 그게 원래도 더
잘한다** — macro 타이밍과 무관하게 발생하는 팩터 강도 효과다. 2026-08-23
findings의 2022년 사례(exposure_frac 0.905로 거의 풀비중인데도 baseline보다
악화)가 바로 이 혼입의 흔적이었다 — 노출은 거의 안 줄었는데 하위 몇 종목만
빠져도 구성이 달라져 그 해엔 반대 방향으로 작용했다.

노출 오버레이(구성 고정)로 이 혼입을 제거하니, **순수 타이밍 효과만으로는
Sharpe가 baseline보다 오히려 낮다**(0.3976 < 0.4556) — 이진 필터(완전
기각, Sharpe 0.3293)보다는 덜 나쁘지만, 방향은 같다. 이는 앞선 결론
(`pbr-macro-rate-regime-check`: 상대적 우위를 설명하는 축과 타이밍 필터로
쓸 축은 다른 질문이다)을 다시 한번 확인한다 — 이번엔 이진이 아니라 연속
버전으로.

## 4. 결론

**"미국10Y 강도에 비례한 PBR 비중 조절"은 노출 효과만으로는 경제적 가치가
없다.** 08-23에 관찰된 개선(MDD·Calmar)은 노출 타이밍이 아니라 랭킹컷이
부수적으로 만든 "더 타이트한 저PBR 스크리닝" 때문이었다 — 이건 이미
알려진 팩터 강도 효과(decile IC)의 재확인이지 새로운 발견이 아니다.

PBR 최종 분류("연구 후보, production alpha 미확정")는 이번에도 안 바뀐다.
타이밍/사이징 경로(이진·연속 둘 다)는 이제 **둘 다 닫혔다** — 다음에
이 방향을 다시 열려면 "언제 살까"가 아니라 "얼마나 타이트하게 스크리닝할까
(topN 자체를 줄이는 독립적인 팩터 강도 실험)"이 별개 질문으로 남는다(이번
조사 범위 밖, 새 실험).

## 5. 파일

- `pbr_exposure_overlay_vs_baseline_mtm.py` — 신규, 노출 오버레이 backtest.
  `build_pbr_sizing_selection.py`의 `exposure_lookup()`을 그대로 import,
  새 selection.json 없음(baseline 그대로 재사용).
- `reports/2026-08-23-pbr-exposure-overlay-vs-baseline-mtm/` — 원자료(raw
  json, gitignore 대상).
- 커밋 안 함(사용자 지시, 이번 세션은 로컬 전용).
